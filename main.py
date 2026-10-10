"""SNOJRC Event Media — upload event photos into folders, let anyone browse and download them.

Folders on disk map directly to pages on the site, e.g.

    media/SNOJRC 2026/SSRS/IMG_0001.jpg  ->  /browse/SNOJRC 2026/SSRS
"""

import os
import re
import secrets
import shutil
import tempfile
import zipfile
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media")).resolve()
CACHE_ROOT = Path(os.environ.get("CACHE_ROOT", BASE_DIR / "cache")).resolve()
SITE_NAME = os.environ.get("SITE_NAME", "SNOJRC Event Media")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SIZES = {"thumb": 480, "preview": 1800}  # longest edge in px for generated copies
INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
# Per request. The upload page sends photos in small batches, so this only needs to fit a few photos.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(12)
    print(f"[!] ADMIN_PASSWORD is not set. Temporary admin password for this run: {ADMIN_PASSWORD}")

MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- helpers


def resolve(rel: str) -> Path:
    """Turn a URL path into a real path inside MEDIA_ROOT, refusing anything that escapes it."""
    path = (MEDIA_ROOT / rel).resolve()
    if path != MEDIA_ROOT and MEDIA_ROOT not in path.parents:
        abort(404)
    if any(part.startswith(".") for part in path.relative_to(MEDIA_ROOT).parts):
        abort(404)
    return path


def rel_of(path: Path) -> str:
    return "" if path == MEDIA_ROOT else path.relative_to(MEDIA_ROOT).as_posix()


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS and path.is_file()


def is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def natural_key(name: str):
    """Sort 'IMG_2' before 'IMG_10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_dir(folder: Path):
    folders, images = [], []
    for entry in folder.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(entry)
        elif is_image(entry):
            images.append(entry)
    # Newest year first on the home page; everything else A-Z.
    folders.sort(key=lambda p: natural_key(p.name), reverse=folder == MEDIA_ROOT)
    images.sort(key=lambda p: natural_key(p.name))
    return folders, images


def images_under(folder: Path):
    return sorted(
        (p for p in folder.rglob("*") if is_image(p) and not is_hidden(p, folder)),
        key=lambda p: [natural_key(part) for part in p.relative_to(folder).parts],
    )


def find_cover(folder: Path):
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=natural_key)
        for name in sorted(files, key=natural_key):
            if Path(name).suffix.lower() in IMAGE_EXTS:
                return Path(root) / name
    return None


def resized(src: Path, size: str) -> Path:
    """Return a cached, downscaled JPEG of src, generating it if missing or stale."""
    out = CACHE_ROOT / size / (rel_of(src) + ".jpg")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.name}.{secrets.token_hex(4)}.tmp")
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # respect phone/camera rotation
        im.thumbnail((SIZES[size], SIZES[size]))
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.save(tmp, "JPEG", quality=85, optimize=True)
    os.replace(tmp, out)  # atomic, so a half-written thumbnail is never served
    return out


def clear_cache(path: Path):
    rel = rel_of(path)
    for size in SIZES:
        cached = CACHE_ROOT / size / rel
        if cached.is_dir():
            shutil.rmtree(cached, ignore_errors=True)
        Path(f"{cached}.jpg").unlink(missing_ok=True)


def unique_path(folder: Path, filename: str) -> Path:
    stem, ext = os.path.splitext(filename)
    candidate, n = folder / filename, 1
    while candidate.exists():
        candidate = folder / f"{stem}_{n}{ext}"
        n += 1
    return candidate


def clean_folder_name(name: str):
    name = INVALID_FOLDER_CHARS.sub("", name).strip().rstrip(".")
    if not name or name.startswith("."):
        return None
    return name[:100]


def zip_name(rel: str) -> str:
    return secure_filename("-".join(Path(rel).parts)) or "photos"


# ---------------------------------------------------------------- admin auth


def is_admin() -> bool:
    return session.get("admin") is True


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("login", next=request.path))
        if request.method == "POST" and not secrets.compare_digest(
            request.form.get("csrf", ""), session.get("csrf", "")
        ):
            abort(400)
        return view(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_globals():
    return {"site_name": SITE_NAME, "is_admin": is_admin(), "csrf": session.get("csrf", "")}


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("browse")
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["admin"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(next_url)
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.route("/admin/logout", methods=["POST"])
@admin_required
def logout():
    session.clear()
    return redirect(url_for("browse"))


# ---------------------------------------------------------------- public pages


@app.route("/")
@app.route("/browse/<path:rel>")
def browse(rel=""):
    folder = resolve(rel)
    if not folder.is_dir():
        abort(404)
    rel = rel_of(folder)
    folders, images = list_dir(folder)

    folder_cards = []
    for f in folders:
        cover = find_cover(f)
        folder_cards.append(
            {
                "name": f.name,
                "rel": rel_of(f),
                "cover": rel_of(cover) if cover else None,
                "count": len(images_under(f)),
            }
        )

    parts = Path(rel).parts
    crumbs = [(part, "/".join(parts[: i + 1])) for i, part in enumerate(parts)]
    return render_template(
        "browse.html",
        rel=rel,
        title=folder.name if rel else "Events",
        crumbs=crumbs,
        folders=folder_cards,
        images=[{"name": p.name, "rel": rel_of(p)} for p in images],
        total=sum(f["count"] for f in folder_cards) + len(images),
    )


@app.route("/photo/<path:rel>")
def original(rel):
    path = resolve(rel)
    if not is_image(path):
        abort(404)
    return send_file(
        path, as_attachment=request.args.get("dl") == "1", download_name=path.name, max_age=86400
    )


@app.route("/thumb/<size>/<path:rel>")
def thumb(size, rel):
    if size not in SIZES:
        abort(404)
    path = resolve(rel)
    if not is_image(path):
        abort(404)
    try:
        out = resized(path, size)
    except Exception:  # unreadable/corrupt image: fall back to the original file
        app.logger.exception("Could not resize %s", path)
        return send_file(path, max_age=3600)
    return send_file(out, mimetype="image/jpeg", max_age=86400)


@app.route("/zip/<path:rel>", methods=["GET", "POST"])
def download_zip(rel):
    """GET: every photo in this folder and its subfolders. POST: only the ticked photos."""
    folder = resolve(rel)
    if not folder.is_dir() or folder == MEDIA_ROOT:
        abort(404)
    rel = rel_of(folder)

    if request.method == "POST":
        files = []
        for name in request.form.getlist("files"):
            path = resolve(f"{rel}/{name}")
            if path.parent == folder and is_image(path):
                files.append(path)
    else:
        files = images_under(folder)
    if not files:
        flash("No photos selected.", "error")
        return redirect(url_for("browse", rel=rel))

    # Photos are already compressed, so store them as-is (much faster than deflating).
    tmp = tempfile.TemporaryFile()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path in files:
            zf.write(path, path.relative_to(folder).as_posix())
    tmp.seek(0)
    return send_file(
        tmp, mimetype="application/zip", as_attachment=True, download_name=f"{zip_name(rel)}.zip"
    )


# ---------------------------------------------------------------- admin actions


@app.route("/admin/upload/<path:rel>", methods=["POST"])
@admin_required
def upload(rel):
    folder = resolve(rel)
    if not folder.is_dir() or folder == MEDIA_ROOT:
        abort(404)

    saved, skipped = 0, []
    for file in request.files.getlist("photos"):
        if not file or not file.filename:
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in IMAGE_EXTS:
            skipped.append(f"{file.filename} (not a supported image type)")
            continue
        try:
            with Image.open(file.stream) as im:
                im.verify()
        except Exception:
            skipped.append(f"{file.filename} (not a valid image)")
            continue
        file.stream.seek(0)

        name = secure_filename(file.filename)
        if Path(name).suffix.lower() != ext:  # e.g. a name made only of non-Latin characters
            name = f"photo-{secrets.token_hex(4)}{ext}"
        file.save(unique_path(folder, name))
        saved += 1

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(saved=saved, skipped=skipped)
    flash(f"Uploaded {saved} photo{'' if saved == 1 else 's'}.", "ok")
    for msg in skipped:
        flash(f"Skipped {msg}", "error")
    return redirect(url_for("browse", rel=rel_of(folder)))


@app.route("/admin/mkdir/", defaults={"rel": ""}, methods=["POST"])
@app.route("/admin/mkdir/<path:rel>", methods=["POST"])
@admin_required
def make_folder(rel):
    parent = resolve(rel)
    if not parent.is_dir():
        abort(404)
    name = clean_folder_name(request.form.get("name", ""))
    if not name:
        flash("Please enter a valid folder name.", "error")
    elif (parent / name).exists():
        flash(f"“{name}” already exists.", "error")
    else:
        (parent / name).mkdir()
        flash(f"Created “{name}”.", "ok")
    return redirect(url_for("browse", rel=rel_of(parent)))


@app.route("/admin/delete/<path:rel>", methods=["POST"])
@admin_required
def delete(rel):
    path = resolve(rel)
    if path == MEDIA_ROOT or not path.exists():
        abort(404)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:  # e.g. on Windows, a file someone is downloading right now is locked
        app.logger.exception("Could not delete %s", path)
        flash(f"Could not fully delete “{path.name}” (in use?). Try again in a moment.", "error")
        return redirect(url_for("browse", rel=rel_of(path if path.exists() else path.parent)))
    clear_cache(path)
    flash(f"Deleted “{path.name}”.", "ok")
    return redirect(url_for("browse", rel=rel_of(path.parent)))


@app.errorhandler(413)
def too_large(_):
    msg = f"Upload too large (limit {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB per batch)."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(error=msg), 413
    flash(msg, "error")
    return redirect(request.referrer or url_for("browse"))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
