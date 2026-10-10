# snojrc-event-media

A small website for sharing event photos. Admins create folders and upload photos; anyone with the link can browse, view, and download single photos, a selection, or a whole folder as a ZIP.

```
SNOJRC 2027/            <- newest year shown first
SNOJRC 2026/
  SSRS/
  SRDU/
  SRIF/
  SRPF/
```

Folders can be nested as deep as you like. Photos live on disk under `media/`, with the same folder structure you see on the site. Thumbnails are generated automatically into `cache/`, which is safe to delete at any time.

## Run locally (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:ADMIN_PASSWORD = "set-your-pw"
.venv\Scripts\python main.py
```

Open http://127.0.0.1:5000, click **Admin login** at the bottom of the page, then create folders and upload photos.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | random, printed at startup | Password for uploading, creating and deleting |
| `SECRET_KEY` | random per start | Signs login cookies. Set a fixed value in production so admins stay logged in across restarts |
| `MEDIA_ROOT` | `./media` | Where photos are stored |
| `CACHE_ROOT` | `./cache` | Where thumbnails are stored |
| `SITE_NAME` | `SNOJRC Event Media` | Title in the header |
| `MAX_UPLOAD_MB` | `200` | Max size of one upload request (the page uploads 5 photos per request) |

## Deploying

Use any host that gives you a **persistent disk**, such as a small VPS, Railway or Render with a volume, or a PythonAnywhere paid plan. Hosts with temporary filesystems (for example, Heroku dynos) will lose uploaded photos.

On a Linux server:

```bash
gunicorn -w 3 -b 0.0.0.0:8000 main:app
```

On Windows: `waitress-serve --port=8000 main:app`

Put it behind HTTPS (most hosts do this for you), and set `ADMIN_PASSWORD` and `SECRET_KEY`.
