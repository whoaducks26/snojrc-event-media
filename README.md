# SNOJRC Event Media

A JRFS-branded media centre for the Singapore National & Open Jump Rope Championship. Athletes, coaches and team managers can browse event folders, preview photos and videos, download individual files, export a selection, or download a whole gallery as a ZIP.

This is a Flask proof of concept with a simple folder-based storage model. It is configured for a password-protected deployment on Render with persistent storage. It is not the event-registration system.

## What the app supports

- Responsive JRFS-branded gallery using the approved crest, colours and typography
- Nested event, category and team folders
- JPG, JPEG, PNG, GIF and WebP photos
- MP4, M4V, MOV and WebM video upload, playback and download
- Automatic photo thumbnails and EXIF rotation
- Single-file, selected-file and whole-folder ZIP downloads
- Separate viewer access code and administrator password
- Admin folder creation, upload and deletion
- CSRF protection for admin actions, login throttling and security headers
- `/health` endpoint for hosting checks

Suggested gallery structure:

```text
SNOJRC 2026/
  Speed/
    SRSS/
    SRDU/
    SRTU/
    DDSS/
  Freestyle/
    SRIF/
    SPRF/
    SRTF/
    WHPF/
  Lion City Long Rope Battle/
```

Folders can be nested as needed. Original uploads live under `MEDIA_ROOT`; generated photo thumbnails live under `CACHE_ROOT` and can be recreated.

## Before you begin

For local use on Windows, install:

- Python 3.11 or newer from [python.org](https://www.python.org/downloads/) with **Add Python to PATH** selected
- Git from [git-scm.com](https://git-scm.com/download/win) if the project will be pushed to GitHub
- A modern browser such as Edge, Chrome or Firefox

For hosting, you also need a GitHub repository and a Render account. The supplied `render.yaml` creates a paid web service and a 10 GB persistent disk, so review Render's current price before confirming the deployment.

## First-time local setup on Windows

Open PowerShell and run the following commands:

```powershell
cd "C:\Users\anson\Documents\snojrc-event-media"

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, allow it only for the current PowerShell window and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Set local credentials in the same PowerShell window. Replace both example passwords with strong, different values:

```powershell
$env:ADMIN_PASSWORD = "replace-with-a-long-unique-admin-password"
$env:ACCESS_PASSWORD = "replace-with-a-separate-viewer-code"
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
```

These variables last only until that PowerShell window is closed. `.env.example` documents the available settings, but the app deliberately does **not** load a `.env` file automatically. Never commit real passwords or secret keys.

Run the tests before first use:

```powershell
python -m unittest discover -s tests -v
```

The tests use temporary storage and do not touch real event media.

## Run the app locally

In the same PowerShell window used for setup:

```powershell
python main.py
```

Open <http://127.0.0.1:5000> in a browser. Enter the viewer code, then select **Admin login** in the footer to create folders and upload media.

On a later day, open a new PowerShell window and repeat only these steps:

```powershell
cd "C:\Users\anson\Documents\snojrc-event-media"
.\.venv\Scripts\Activate.ps1

$env:ADMIN_PASSWORD = "your-admin-password"
$env:ACCESS_PASSWORD = "your-viewer-code"
$env:SECRET_KEY = "your-stable-local-secret-key"

python main.py
```

Use the same `SECRET_KEY` when you want existing browser sessions to remain valid after a restart. If it changes, users simply need to log in again.

To confirm that the server is healthy:

```powershell
(Invoke-WebRequest http://127.0.0.1:5000/health).Content
```

## Stop or restart the local app

Return to the PowerShell window running the app and press `Ctrl+C`. Wait until the PowerShell prompt returns. Uploaded originals remain in `media`; stopping the server does not delete them.

To restart, run:

```powershell
python main.py
```

If the original window was closed but port 5000 is still in use, identify and stop only the process listening on that port:

```powershell
$appProcessId = Get-NetTCPConnection -LocalPort 5000 -State Listen |
    Select-Object -First 1 -ExpandProperty OwningProcess
Stop-Process -Id $appProcessId
```

Do not terminate every Python process, because other Python applications may also be running.

## Local data and backups

- `media/` contains original uploads and is the important local data directory.
- `cache/` contains generated thumbnails and can be rebuilt.
- Deleting a folder in the admin interface permanently deletes its originals and cached thumbnails.
- Keep the original event media in a separate controlled archive. Do not use this proof-of-concept site as the only copy.
- Common browser playback is most reliable with MP4 video encoded as H.264 video plus AAC audio. Other accepted formats remain downloadable even if a browser cannot preview their codec.

Both `media/` and `cache/` are excluded from Git and must not be pushed to GitHub.

## Configuration

| Variable | Local default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | Random per start | Separate credential for create, upload and delete actions |
| `ACCESS_PASSWORD` | Empty/public | Shared viewer code; required in hosted mode |
| `SECRET_KEY` | Random per start | Signs sessions; must be stable in production |
| `MEDIA_ROOT` | `./media` | Persistent original photo and video storage |
| `CACHE_ROOT` | `./cache` | Re-creatable photo thumbnail storage |
| `SITE_NAME` | `SNOJRC Event Media` | Header and product name |
| `EVENT_NAME` | 2026 championship full name | Accessible event name |
| `EVENT_SHORT_NAME` | `SNOJRC 2026` | Compact event label |
| `EVENT_DATE` | `28 November 2026` | Hero event detail |
| `EVENT_VENUE` | `Changi Simei Community Club` | Hero event detail |
| `CONTACT_EMAIL` | `connect@jrfs.org.sg` | General event enquiry contact |
| `PRIVACY_EMAIL` | `admin@jrfs.org.sg` | Privacy and media-removal contact |
| `MAX_UPLOAD_MB` | `500` | Maximum size of one upload; the UI sends one file per request |
| `SESSION_COOKIE_SECURE` | On in hosted mode | Sends session cookies over HTTPS only |
| `TRUST_PROXY` | On in hosted mode | Trusts the documented hosting reverse proxy |
| `PRODUCTION` | Off | Enables fail-closed hosted checks |

If `ACCESS_PASSWORD` is omitted locally, the gallery is public. If `ADMIN_PASSWORD` is omitted locally, a temporary password is printed at startup. Hosted mode intentionally refuses to start when either password is missing.

## Deploy to Render

The repository includes `render.yaml`, which defines:

- a Python web service in Render's Singapore region;
- Gunicorn with a health check at `/health`;
- a 10 GB persistent disk mounted at `/var/data`;
- originals at `/var/data/media` and cache at `/var/data/cache`;
- a generated session secret and prompted viewer/admin credentials.

Only data written under `/var/data` survives a Render restart or redeployment. Do not change `MEDIA_ROOT` or `CACHE_ROOT` to paths outside that mounted disk.

### 1. Check and push the code

From the project directory, run the tests and review the pending files:

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
git status
git diff
```

Stage the application files explicitly so that local media and private reference material are not added accidentally:

```powershell
git add .gitignore .env.example README.md main.py render.yaml requirements.txt static templates tests
git diff --cached
git commit -m "Prepare SNOJRC event media site for deployment"
git push -u origin HEAD
```

The brand-guideline HTML and event-handbook PDF are reference documents, not runtime dependencies. Add them to Git only if JRFS wants them version-controlled and their distribution is permitted.

If `git push` reports that no remote exists, first create a private repository on GitHub and follow GitHub's instructions to add it as `origin`. Do not upload the `media/`, `cache/`, `.venv/` or `.env` directories.

### 2. Create the Render service

1. Sign in to the [Render Dashboard](https://dashboard.render.com/).
2. Select **New → Blueprint** and connect the GitHub repository.
3. Select the reviewed branch. Render will read `render.yaml` from the repository root.
4. Enter strong, different values when prompted for `ACCESS_PASSWORD` and `ADMIN_PASSWORD`.
5. Confirm the Singapore region, paid web-service plan and 10 GB persistent disk. Review the displayed monthly charge before creating the resources.
6. Deploy and follow the build log. The build installs `requirements.txt`; the service starts with Gunicorn.
7. When the service is healthy, open its generated `onrender.com` address.

`SECRET_KEY` is generated by Render. Do not replace it during routine redeployments, or all existing sessions will be signed out.

### 3. Complete the deployment smoke test

Before sharing the site:

1. Confirm an incorrect viewer code fails and the correct code opens the gallery.
2. Log in as admin and create a disposable test folder.
3. Upload one JPG and one short MP4.
4. Preview both files, download each file, then download the folder ZIP.
5. Delete the disposable test folder.
6. Trigger a redeploy and confirm genuine event media remains available afterward.
7. Open `/health` on the deployed URL and confirm it returns a healthy response.

If uploaded files disappear after a redeploy, stop adding media and verify that the disk is mounted at `/var/data` and both storage variables point inside it.

### 4. Add a custom domain

After the staging URL is approved:

1. Open the service's **Settings → Custom Domains** section in Render.
2. Add the intended JRFS subdomain.
3. Create the exact DNS records Render displays at the domain's DNS provider.
4. Wait for Render to verify the domain and issue HTTPS.
5. Repeat the viewer, admin, upload and download smoke tests on the custom domain before distributing it.

Do not publish the address until the access code, media rights, privacy contact and removal process have been approved.

## Update, redeploy or take the hosted site offline

For a normal update, test and push another commit to the branch linked in Render:

```powershell
python -m unittest discover -s tests -v
git status
git add README.md
git diff --cached
git commit -m "Describe the update"
git push
```

`git add README.md` is only an example. Replace it with the specific files reviewed for that update; avoid `git add .` when the working folder contains private reference documents.

Render normally deploys each new commit to the linked branch. A code rollback does not roll back or restore uploaded media, because the disk has a separate lifecycle.

For a short planned outage, enable **Maintenance Mode** in the Render service settings. This blocks public traffic without deleting the service or disk. Disable it to bring the site back. For a longer shutdown, use Render's suspend control if available for the workspace, but confirm the persistent disk and its billing/retention state first.

Do not delete the Render service or disk merely to stop public access. Deletion can make uploaded media unrecoverable.

Official hosting references:

- [Deploy a Flask app on Render](https://render.com/docs/deploy-flask)
- [Render Blueprints](https://render.com/docs/infrastructure-as-code)
- [Persistent disks](https://render.com/docs/disks)
- [Maintenance mode](https://render.com/docs/maintenance-mode)
- [Custom domains](https://render.com/docs/custom-domains)

## Troubleshooting

| Problem | Check |
|---|---|
| `python` or `py` is not recognised | Install Python and reopen PowerShell; verify with `py --version` |
| `ModuleNotFoundError` | Activate `.venv` and run `python -m pip install -r requirements.txt` |
| Port 5000 is already in use | Stop the existing listener as shown above, or set `$env:PORT = "5001"` before starting |
| A temporary admin password appears | `ADMIN_PASSWORD` was not set in the current PowerShell window |
| Hosted app fails during startup | Set both `ADMIN_PASSWORD` and `ACCESS_PASSWORD` in Render's Environment settings |
| Upload returns `413` | The file exceeds `MAX_UPLOAD_MB` or a hosting request-size limit |
| Video downloads but will not play inline | Re-encode it as MP4 with H.264 video and AAC audio |
| Uploads disappear after redeployment | Verify the persistent disk and `/var/data/media` configuration immediately |
| First photo view is slow | The thumbnail is being generated; later views use the cache |

Render build and runtime failures are shown in the service's **Logs** page. Never paste passwords, secret keys or private media URLs into a public issue or support post.

## Go-live checklist

- Use different, long passwords for viewer and administrator access.
- Share the admin password only with authorised operators.
- Confirm who may view, download and redistribute event media.
- Confirm the retention period and media-removal contact.
- Keep an off-platform copy of every original upload.
- Check available disk space before and during the event.
- Test the site on both a phone and a desktop browser.
- Verify that no real secret is committed with `git diff` and `git status`.
- Rotate the viewer code after unintended disclosure or when the approved audience changes.

## Production boundary

This design is suitable for a controlled proof of concept and a modest single-instance event gallery. Before a high-volume or long-term public launch:

- confirm the audience, download rights and retention period with JRFS's data-protection owner;
- keep the viewer gate enabled unless public redistribution is explicitly approved;
- establish an off-platform backup and test restoration;
- move originals to object storage such as R2 or S3 if media volume, concurrent downloads or archival needs grow;
- replace the shared admin password with named staff accounts and audit logging if multiple administrators need access;
- consider queued ZIP creation for very large video galleries.

The footer links to JRFS's published data-protection policy and provides a contact route for access, correction or media-removal requests.
