# Village Information Portal — Flask Edition

A small village/panchayat information site: public pages for services, events,
announcements, and complaint submission, plus an admin dashboard to manage all of it.

This is a **Flask** app, built to deploy cleanly on **Vercel's Python
runtime** (no persistent disk, so media files live on Cloudinary and the
database is Postgres/Neon in production). JWT cookie auth is used instead of
Flask-Login so the auth check works the same whether the app is warm or a
fresh serverless cold start.

---

## 1. Project structure

```
village-portal/
├── main.py               # Flask app + all routes
├── database.py           # SQLAlchemy engine, session, models (Admin, Service, Event, EventMedia, Announcement, Complaint)
├── auth.py               # Password hashing + JWT cookie auth (login_required decorator)
├── schemas.py             # Pydantic request/response validation models
├── requirements.txt
├── vercel.json            # Vercel Functions config (main.py entrypoint)
├── .env.example            # copy to .env and fill in real values
├── templates/
│   ├── index.html          # public homepage (includes each event's media gallery)
│   ├── admin_login.html
│   └── admin_dashboard.html    # includes the "Media" modal for uploading event files
├── static/                 # served by Flask locally (app.static_folder)
│   ├── css/style.css
│   └── js/main.js
└── public/                 # mirror of static/, served by Vercel's CDN in production
    └── static/
        ├── css/style.css
        └── js/main.js
```

Both `static/` and `public/static/` contain the same CSS/JS. Locally, Flask
serves `/static/...` from `static/`. On Vercel, files under `public/**` are
served straight from the CDN at the same paths (Vercel's guidance is not to
route static assets through `app.static_folder` in production) — so keep the
two directories in sync if you edit `style.css` or `main.js`.

Event media (photos/videos/documents) is **not** stored under `static/` or
`public/` — see below.

---

## 1a. Event media (photos, videos, documents)

Each event can have **any number** of photos, videos, and documents attached —
there's no cap in the code, and nothing expires. All media (photos, videos,
*and* documents) is stored on **Cloudinary**, a free cloud media host, not on
the app server's disk.

- **Why cloud storage, not local disk**: most free deployment platforms
  (Vercel, Render, Railway, Fly.io free tiers, etc.) either give you no
  persistent disk at all, or wipe whatever's on disk every time you redeploy
  or the instance restarts. Anything saved locally would eventually vanish.
- **Why Cloudinary specifically**: free forever, **no credit card required**
  to sign up, and its free tier (25 credits/month — 1 credit ≈ 1 GB storage
  or bandwidth) comfortably covers a single village portal's worth of media.
- **Persistence**: uploaded files stay in the cloud indefinitely with no
  expiry date; they're only removed when an admin deletes that file (or the
  whole event).
- **Setup required**: sign up free at
  https://cloudinary.com/users/register_free, then copy **Cloud name**,
  **API Key**, and **API Secret** (Dashboard → Settings → Access Keys) into
  `.env` as `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`,
  `CLOUDINARY_API_SECRET`. Uploads return a clear 503 error until these are set.
- **Allowed file types**: images (`.jpg .jpeg .png .gif .webp .bmp .heic`),
  video (`.mp4 .mov .avi .mkv .webm .m4v`), and documents
  (`.pdf .doc .docx .xls .xlsx .ppt .pptx .txt .csv`). Anything else is
  rejected with a 400 error. Photos/videos upload as Cloudinary's `image`/
  `video` resource types; documents upload as its `raw` type.
- **Admin routes** (require login): `POST /api/events/<event_id>/media`
  (multipart, field name `files`, accepts multiple files in one request),
  `DELETE /api/events/<event_id>/media/<media_id>` (also deletes the file
  from Cloudinary).
- **Public route**: `GET /api/events/<event_id>/media` returns the list of
  files as JSON (each with a working direct Cloudinary `url`); the homepage
  renders it as a gallery (photos/videos inline, documents as a downloadable
  link) without needing to log in. `GET /media/<media_id>/download` redirects
  to a URL that forces a real file download instead of opening inline.

---

## 2. Run it from scratch (local machine)

### Step 1 — Install Python
You need **Python 3.10+**. Check with:
```bash
python3 --version
```

### Step 2 — Get the project folder
Unzip the project, then open a terminal inside it:
```bash
cd village-portal
```

### Step 3 — Create a virtual environment (recommended)
```bash
python3 -m venv venv

# activate it:
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows (cmd/powershell)
```

### Step 4 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 5 — Configure environment variables
```bash
cp .env.example .env
```
Open `.env` and set a real `SECRET_KEY`. Generate one with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output as the value of `SECRET_KEY` in `.env`.

### Step 6 — Run the server
```bash
flask --app main run --debug
```
or simply:
```bash
python main.py
```
You should see the "Admin user created!" message on first run (username
`admin`, password `admin123` — **change this immediately**, see §4).

Visit:
- Public site: http://localhost:8000
- Admin login: http://localhost:8000/admin/login

---

## 3. How the pieces talk to each other

1. **Public visitor** hits `/` → Flask queries the DB for services, events,
   announcements, complaints → renders `index.html` with that data.
2. **Complaint form** on the homepage posts JSON to `/api/public/complaints`
   (no login needed) → validated by the `PublicComplaintIn` Pydantic model →
   saved → JSON response read by the inline `<script>` in `index.html`.
3. **Admin login** posts a form to `/admin/login` → password checked with
   `passlib` → on success, a signed JWT is set in an `HttpOnly` cookie →
   browser is redirected to `/admin/dashboard`.
4. **Dashboard and all `/api/...` admin routes** are wrapped in the
   `@login_required` decorator (`auth.py`), which reads that cookie, verifies
   the JWT signature and expiry, and loads the matching `Admin` row. No
   cookie or a bad/expired one → redirected back to `/admin/login`.
5. **Dashboard's add/edit/delete buttons** (in `main.js` /
   `admin_dashboard.html`'s inline script) call the same `/api/services`,
   `/api/events`, `/api/announcements`, `/api/complaints` endpoints — same
   URLs, same JSON shapes, so the existing JS needs no changes.

---

## 4. Before you put this in front of real users

- **Change the default admin password.** Log in with `admin` / `admin123`
  once, then add a small one-off script or shell into the DB to update the
  password hash — or extend `main.py` with a "change password" admin route.
  Don't ship the default credentials live.
- **Set a real `SECRET_KEY`** in `.env` — never use the placeholder value in
  production. Anyone who has it can forge admin login tokens.
- **Switch SQLite → Postgres** for anything beyond local development (see
  §6) — SQLite is fine for development and very low traffic, but doesn't
  handle concurrent writes well, and Vercel (and most other free hosts) has
  no persistent disk at all.
- **Serve over HTTPS** — cookies are already marked `Secure` automatically
  once `IS_PRODUCTION` in `main.py` detects Vercel's own `VERCEL` env var (or
  set `FORCE_HTTPS=1` on any other host served over HTTPS).
- **Restrict CORS** if you ever split frontend and backend onto different
  domains (right now everything is served from the same Flask app, so this
  isn't needed yet) — set `ALLOWED_ORIGINS` in `.env`.

---

## 5. Useful commands during development

```bash
# Run with auto-reload on code changes
flask --app main run --debug

# Run on a specific port
flask --app main run --debug --port 8080

# Run through Vercel's local dev server (matches the production runtime)
vercel dev
```

---

## 6. Deploying to Vercel (what this repo is set up for)

This repo already includes a `vercel.json` and a `database.py` that
auto-detects Postgres vs SQLite, so deploying needs almost no extra setup.
Vercel's Python runtime auto-detects Flask from `requirements.txt` and looks
for a `Flask` instance named `app` in `main.py` — no build config beyond
`vercel.json`'s `maxDuration` setting is required.

**Why Neon (Postgres) instead of SQLite:** Vercel's Python functions have
**no persistent disk at all** — every request can hit a different,
short-lived instance, so SQLite (a single file on disk) does not work here;
you'd lose all data constantly. Neon is a serverless Postgres provider with a
free tier built for exactly this kind of stateless hosting, including its own
connection pooler (important because many Vercel function instances may try
to connect at once).

1. **Create the database:**
   - Sign up free at https://neon.tech (no credit card required).
   - Create a project, then open **Connection Details** and copy the
     connection string that uses the **pooled** host (hostname contains
     `-pooler`).
2. **Push this project to GitHub** (a plain repo, no special config needed).
3. **Import into Vercel:**
   - https://vercel.com/new → Import your GitHub repo.
   - Vercel detects the Flask app automatically from `requirements.txt` and
     `main.py` — no framework preset needed.
4. **Set environment variables** (Vercel dashboard → Project → Settings →
   Environment Variables):
   - `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
   - `DATABASE_URL` — the Neon pooled connection string from step 1
   - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` — from Cloudinary
   - `ALLOWED_ORIGINS` — leave unset for now; fill in once you have an app origin to lock CORS down to (see §8)
5. **Deploy.** Vercel gives you `https://your-project.vercel.app` with HTTPS
   already on, which is why cookies are marked `Secure` automatically in this
   setup (`IS_PRODUCTION` in `main.py` detects Vercel's own `VERCEL` env var).
6. First request after each deploy runs `init_db()` (creates tables if
   missing) and creates the default `admin`/`admin123` account if it doesn't
   already exist — **change that password immediately** by logging in and
   updating it (or update the row directly in Neon's SQL editor), since a
   public Vercel URL means that login page is reachable by anyone.
7. Every `git push` to your main branch auto-redeploys; pull requests get
   their own preview URL for free.
8. **Static assets**: CSS/JS are served from `public/static/**` on Vercel
   (straight from the CDN, bypassing the Flask function) — if you edit
   `static/css/style.css` or `static/js/main.js`, copy the same change into
   `public/static/...` before deploying, or the live site won't pick it up.

**Local development still works exactly as in §2** — without a `DATABASE_URL`
env var set, it falls back to local SQLite, so day-to-day coding doesn't
require touching Neon at all. Only the deployed (Vercel) environment needs
`DATABASE_URL` pointed at Neon.

### Other hosting options (Render, Railway, a VPS)

These all work too, and don't need the `public/` static-asset split — Flask's
own `static/` folder serves fine on them since they use a normal long-lived
process instead of Vercel's per-request functions.

- **Render / Railway**: build command `pip install -r requirements.txt`,
  start command `gunicorn main:app`. Add a Postgres add-on and point
  `DATABASE_URL` at it (SQLite is wiped on every redeploy on these platforms'
  free tiers too).
- **A VPS** (DigitalOcean, Hetzner, AWS Lightsail): install deps in a venv,
  run behind a process manager, e.g. `gunicorn main:app -w 2 -b 0.0.0.0:8000`,
  put Nginx in front as a reverse proxy, and use Certbot for a free HTTPS
  certificate.

---

## 7. Later: turning this into an APK

This backend is already API-shaped (every admin action goes through JSON
endpoints under `/api/...`), which gives you two realistic paths once you're
ready to build a mobile app:

- **Fastest — wrap the deployed site:** once it's live on Vercel, tools like
  [Capacitor](https://capacitorjs.com/) or [Median](https://median.co/) (or
  Android's own WebView in a minimal native shell) can package the public
  URL as an installable APK with very little extra code.
- **More native — a real mobile app that talks to the API:** build with
  Flutter or React Native and call the same `/api/services`, `/api/events`,
  `/api/announcements`, `/api/complaints` endpoints this backend already
  exposes, instead of re-rendering the server's HTML templates. Admin
  endpoints will need the app to send the JWT the same way the browser
  cookie does (e.g. as an `Authorization: Bearer <token>` header — a small
  addition to `auth.py` would accept either the cookie or that header).

Either path is why CORS (`ALLOWED_ORIGINS` in `.env.example`) and the
`/api/health` endpoint were added — set `ALLOWED_ORIGINS` to your app's real
origin once you know it, instead of leaving it wide open.

---

## 8. Quick troubleshooting

- **"ModuleNotFoundError" on startup** → you forgot to activate the venv or
  run `pip install -r requirements.txt`.
- **Login redirects back to the login page even with correct password** →
  check that `SECRET_KEY` in `.env` didn't change between when the user
  logged in and now (changing it invalidates all existing tokens — that's
  expected and fine, just log in again).
- **Data disappears after redeploy on Render/Railway free tier** → you're
  still on SQLite; switch to their free Postgres add-on.
- **CSS/JS not loading locally** → confirm the app was started from inside
  the `village-portal/` folder so the relative `static/` and `templates/`
  paths resolve correctly.
- **CSS/JS not loading on Vercel** → make sure the same files also exist
  under `public/static/...` (see §6, step 8) — Vercel serves static assets
  from `public/**`, not from Flask's `static_folder`.
