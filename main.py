"""SNOJRC event media library.

Folders on disk map directly to gallery pages, for example::

    media/SNOJRC 2026/SRSS/IMG_0001.jpg -> /browse/SNOJRC 2026/SRSS

The application intentionally keeps its storage model simple for the proof of
concept. Production deployments must mount ``MEDIA_ROOT`` on persistent
storage; the supplied Render Blueprint does this under ``/var/data``.
"""

from __future__ import annotations

import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    Response,
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
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media")).resolve()
CACHE_ROOT = Path(os.environ.get("CACHE_ROOT", BASE_DIR / "cache")).resolve()
SITE_NAME = os.environ.get("SITE_NAME", "SNOJRC Event Media")
EVENT_NAME = os.environ.get(
    "EVENT_NAME", "Singapore National & Open Jump Rope Championship 2026"
)
EVENT_SHORT_NAME = os.environ.get("EVENT_SHORT_NAME", "SNOJRC 2026")
EVENT_DATE = os.environ.get("EVENT_DATE", "28 November 2026")
EVENT_VENUE = os.environ.get("EVENT_VENUE", "Changi Simei Community Club")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "connect@jrfs.org.sg")
PRIVACY_EMAIL = os.environ.get("PRIVACY_EMAIL", "admin@jrfs.org.sg")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
SIZES = {"thumb": 640, "preview": 1800}
INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

HOSTED = env_flag("RENDER") or env_flag("PRODUCTION")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD")

if HOSTED and not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD must be set for a hosted deployment")
if HOSTED and not ACCESS_PASSWORD:
    raise RuntimeError("ACCESS_PASSWORD must be set for a hosted deployment")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(12)
    print(f"[!] ADMIN_PASSWORD is not set. Temporary admin password: {ADMIN_PASSWORD}")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE", HOSTED),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

if env_flag("TRUST_PROXY", HOSTED):
    # Render and the documented deployment path use one trusted HTTPS proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- storage helpers


def resolve(rel: str) -> Path:
    """Resolve a URL path inside MEDIA_ROOT and reject traversal/hidden paths."""
    path = (MEDIA_ROOT / rel).resolve()
    if path != MEDIA_ROOT and MEDIA_ROOT not in path.parents:
        abort(404)
    if any(part.startswith(".") for part in path.relative_to(MEDIA_ROOT).parts):
        abort(404)
    return path


def rel_of(path: Path) -> str:
    return "" if path == MEDIA_ROOT else path.relative_to(MEDIA_ROOT).as_posix()


def media_kind(path: Path) -> str | None:
    resolved = path.resolve()
    if resolved == MEDIA_ROOT or MEDIA_ROOT not in resolved.parents:
        return None
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS and path.is_file():
        return "image"
    if suffix in VIDEO_EXTS and path.is_file():
        return "video"
    return None


def is_media(path: Path) -> bool:
    return media_kind(path) is not None


def is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def natural_key(name: str):
    """Sort ``IMG_2`` before ``IMG_10``."""
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", name)]


def list_dir(folder: Path):
    folders, media = [], []
    for entry in folder.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            folders.append(entry)
        elif is_media(entry):
            media.append(entry)
    folders.sort(key=lambda path: natural_key(path.name), reverse=folder == MEDIA_ROOT)
    media.sort(key=lambda path: natural_key(path.name))
    return folders, media


def media_under(folder: Path):
    return sorted(
        (path for path in folder.rglob("*") if is_media(path) and not is_hidden(path, folder)),
        key=lambda path: [natural_key(part) for part in path.relative_to(folder).parts],
    )


def find_cover(folder: Path):
    """Prefer a photo cover; fall back to the first video when a folder is video-only."""
    first_video = None
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted((name for name in dirs if not name.startswith(".")), key=natural_key)
        for name in sorted(files, key=natural_key):
            path = Path(root) / name
            kind = media_kind(path)
            if kind == "image":
                return path
            if kind == "video" and first_video is None:
                first_video = path
    return first_video


def resized(src: Path, size: str) -> Path:
    """Return a cached, downscaled JPEG for a source image."""
    out = CACHE_ROOT / size / (rel_of(src) + ".jpg")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.name}.{secrets.token_hex(4)}.tmp")
    with Image.open(src) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((SIZES[size], SIZES[size]))
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(tmp, "JPEG", quality=86, optimize=True)
    os.replace(tmp, out)
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
    candidate, number = folder / filename, 1
    while candidate.exists():
        candidate = folder / f"{stem}_{number}{ext}"
        number += 1
    return candidate


def clean_folder_name(name: str):
    name = INVALID_FOLDER_CHARS.sub("", name).strip().rstrip(".")
    if not name or name.startswith("."):
        return None
    return name[:100]


def zip_name(rel: str) -> str:
    return secure_filename("-".join(Path(rel).parts)) or "event-media"


def valid_video_header(file) -> bool:
    """Reject renamed arbitrary files while allowing browser-oriented containers."""
    header = file.stream.read(16)
    file.stream.seek(0)
    ext = Path(file.filename or "").suffix.lower()
    if ext == ".webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    return len(header) >= 12 and header[4:8] == b"ftyp"


def set_media_cache(response):
    response.cache_control.public = not bool(ACCESS_PASSWORD)
    response.cache_control.private = bool(ACCESS_PASSWORD)
    response.cache_control.max_age = 86400
    return response


# ---------------------------------------------------------------- access and security


FAILED_ATTEMPTS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 10


def client_key(scope: str) -> tuple[str, str]:
    return scope, request.remote_addr or "unknown"


def login_rate_limited(scope: str) -> bool:
    now = time.monotonic()
    attempts = FAILED_ATTEMPTS[client_key(scope)]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_FAILURES


def record_login_failure(scope: str):
    FAILED_ATTEMPTS[client_key(scope)].append(time.monotonic())


def clear_login_failures(scope: str):
    FAILED_ATTEMPTS.pop(client_key(scope), None)


def safe_next(value: str | None, default: str) -> str:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return default
    return value


def is_admin() -> bool:
    return session.get("admin") is True


def can_view() -> bool:
    return not ACCESS_PASSWORD or session.get("viewer") is True or is_admin()


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


@app.before_request
def require_viewer_access():
    if can_view():
        return None
    if request.endpoint in {"access", "login", "health", "robots", "static"}:
        return None
    target = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    return redirect(url_for("access", next=target))


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Robots-Tag", "noindex, noarchive")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; media-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com",
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.context_processor
def inject_globals():
    return {
        "site_name": SITE_NAME,
        "event_name": EVENT_NAME,
        "event_short_name": EVENT_SHORT_NAME,
        "event_date": EVENT_DATE,
        "event_venue": EVENT_VENUE,
        "contact_email": CONTACT_EMAIL,
        "privacy_email": PRIVACY_EMAIL,
        "is_admin": is_admin(),
        "viewer_authorized": can_view(),
        "access_protected": bool(ACCESS_PASSWORD),
        "csrf": session.get("csrf", ""),
    }


@app.route("/access", methods=["GET", "POST"])
def access():
    if not ACCESS_PASSWORD:
        return redirect(url_for("browse"))
    next_url = safe_next(request.values.get("next"), url_for("browse"))
    if request.method == "POST":
        if login_rate_limited("viewer"):
            flash("Too many attempts. Please wait 15 minutes and try again.", "error")
            return render_template("access.html", next_url=next_url), 429
        if secrets.compare_digest(request.form.get("password", ""), ACCESS_PASSWORD):
            clear_login_failures("viewer")
            session.clear()
            session.permanent = True
            session["viewer"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(next_url)
        record_login_failure("viewer")
        flash("That access code is not recognised.", "error")
    return render_template("access.html", next_url=next_url)


@app.route("/access/logout", methods=["POST"])
def access_logout():
    if not secrets.compare_digest(
        request.form.get("csrf", ""), session.get("csrf", "")
    ):
        abort(400)
    session.clear()
    return redirect(url_for("access"))


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    next_url = safe_next(request.values.get("next"), url_for("browse"))
    if request.method == "POST":
        if login_rate_limited("admin"):
            flash("Too many attempts. Please wait 15 minutes and try again.", "error")
            return render_template("login.html", next_url=next_url), 429
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            clear_login_failures("admin")
            session.clear()
            session.permanent = True
            session["viewer"] = True
            session["admin"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(next_url)
        record_login_failure("admin")
        flash("That admin password is not recognised.", "error")
    return render_template("login.html", next_url=next_url)


@app.route("/admin/logout", methods=["POST"])
@admin_required
def logout():
    session.clear()
    return redirect(url_for("access") if ACCESS_PASSWORD else url_for("browse"))


# ---------------------------------------------------------------- public pages


@app.route("/health")
def health():
    healthy = MEDIA_ROOT.is_dir() and CACHE_ROOT.is_dir()
    return jsonify(status="ok" if healthy else "error"), 200 if healthy else 503


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


@app.route("/")
@app.route("/browse/<path:rel>")
def browse(rel=""):
    folder = resolve(rel)
    if not folder.is_dir():
        abort(404)
    rel = rel_of(folder)
    folders, media = list_dir(folder)

    folder_cards = []
    for child in folders:
        cover = find_cover(child)
        folder_cards.append(
            {
                "name": child.name,
                "rel": rel_of(child),
                "cover": rel_of(cover) if cover else None,
                "cover_kind": media_kind(cover) if cover else None,
                "count": len(media_under(child)),
            }
        )

    parts = Path(rel).parts
    crumbs = [(part, "/".join(parts[: index + 1])) for index, part in enumerate(parts)]
    media_cards = [
        {
            "name": path.name,
            "rel": rel_of(path),
            "kind": media_kind(path),
            "type_label": "Video" if media_kind(path) == "video" else "Photo",
        }
        for path in media
    ]
    return render_template(
        "browse.html",
        rel=rel,
        title=folder.name if rel else "Competition galleries",
        crumbs=crumbs,
        folders=folder_cards,
        media=media_cards,
        total=sum(card["count"] for card in folder_cards) + len(media_cards),
    )


@app.route("/media/<path:rel>")
def original(rel):
    path = resolve(rel)
    kind = media_kind(path)
    if not kind:
        abort(404)
    download = request.args.get("dl") == "1"
    mimetype = mimetypes.guess_type(path.name)[0]
    response = send_file(
        path,
        as_attachment=download,
        download_name=path.name,
        conditional=True,
        mimetype=mimetype,
    )
    return set_media_cache(response)


@app.route("/thumb/<size>/<path:rel>")
def thumb(size, rel):
    if size not in SIZES:
        abort(404)
    path = resolve(rel)
    if media_kind(path) != "image":
        abort(404)
    try:
        out = resized(path, size)
    except Exception:
        app.logger.exception("Could not resize %s", path)
        return set_media_cache(send_file(path, conditional=True))
    return set_media_cache(send_file(out, mimetype="image/jpeg", conditional=True))


@app.route("/zip/<path:rel>", methods=["GET", "POST"])
def download_zip(rel):
    """GET downloads a folder tree; POST downloads only selected direct children."""
    folder = resolve(rel)
    if not folder.is_dir() or folder == MEDIA_ROOT:
        abort(404)
    rel = rel_of(folder)

    if request.method == "POST":
        files = []
        for name in request.form.getlist("files"):
            path = resolve(f"{rel}/{name}")
            if path.parent == folder and is_media(path):
                files.append(path)
    else:
        files = media_under(folder)
    if not files:
        flash("No media selected.", "error")
        return redirect(url_for("browse", rel=rel))

    archive = tempfile.TemporaryFile()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED, allowZip64=True) as output:
        for path in files:
            output.write(path, path.relative_to(folder).as_posix())
    archive.seek(0)
    response = send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{zip_name(rel)}.zip",
    )
    response.cache_control.no_store = True
    return response


# ---------------------------------------------------------------- admin actions


@app.route("/admin/upload/<path:rel>", methods=["POST"])
@admin_required
def upload(rel):
    folder = resolve(rel)
    if not folder.is_dir() or folder == MEDIA_ROOT:
        abort(404)

    saved, skipped = 0, []
    for file in request.files.getlist("media"):
        if not file or not file.filename:
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in MEDIA_EXTS:
            skipped.append(f"{file.filename} (unsupported file type)")
            continue

        if ext in IMAGE_EXTS:
            try:
                with Image.open(file.stream) as image:
                    image.verify()
            except Exception:
                skipped.append(f"{file.filename} (not a valid image)")
                continue
            finally:
                file.stream.seek(0)
        elif not valid_video_header(file):
            skipped.append(f"{file.filename} (not a valid MP4/MOV/WebM video)")
            continue

        name = secure_filename(file.filename)
        if Path(name).suffix.lower() != ext:
            name = f"media-{secrets.token_hex(4)}{ext}"
        file.save(unique_path(folder, name))
        saved += 1

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(saved=saved, skipped=skipped)
    flash(f"Uploaded {saved} file{'' if saved == 1 else 's'}.", "ok")
    for message in skipped:
        flash(f"Skipped {message}", "error")
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
    except OSError:
        app.logger.exception("Could not delete %s", path)
        flash(f"Could not fully delete “{path.name}”. Try again in a moment.", "error")
        return redirect(url_for("browse", rel=rel_of(path if path.exists() else path.parent)))
    clear_cache(path)
    flash(f"Deleted “{path.name}”.", "ok")
    return redirect(url_for("browse", rel=rel_of(path.parent)))


@app.errorhandler(413)
def too_large(_error):
    limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    message = f"Upload too large (limit {limit} MB per file batch)."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(error=message), 413
    flash(message, "error")
    return redirect(request.referrer or url_for("browse"))


@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        code=404,
        heading="Gallery not found",
        message="This gallery may have moved, expired, or been removed.",
    ), 404


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG"),
    )
