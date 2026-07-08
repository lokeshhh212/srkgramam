"""
Village Information Portal - Flask version.

This replaces the FastAPI app. Key mapping from FastAPI -> Flask:
  - @app.get/post/put/delete(...)     -> @app.route(..., methods=[...])
  - Jinja2Templates().TemplateResponse -> render_template(...)
  - Pydantic model as a function param -> schema.model_validate(request.get_json())
  - Depends(get_current_admin)         -> @login_required decorator (see auth.py)
  - Depends(get_db) / yield session    -> g.db, opened per-request, closed in teardown
  - HTTPException(status_code, detail) -> jsonify({"detail": ...}), status_code

Run locally with:  flask --app main run --debug
Or simply:          python main.py
"""
import os
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()  # reads .env into os.environ before anything else initializes

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

from flask import Flask, request, g, render_template, redirect, url_for, jsonify, make_response
from flask_cors import CORS
from pydantic import ValidationError

from database import init_db, SessionLocal, Admin, Service, Event, EventMedia, Announcement, Complaint
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    login_required,
    COOKIE_NAME,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from schemas import (
    ServiceIn, ServiceOut,
    EventIn, EventOut,
    EventMediaOut,
    AnnouncementIn, AnnouncementOut,
    ComplaintIn, ComplaintOut, PublicComplaintIn,
)

# ===== EVENT MEDIA STORAGE (Cloudinary - free cloud media host) =====
# Why cloud storage instead of local disk: most free hosting platforms (Render,
# Railway, Fly.io free tiers, Vercel, etc.) either have no persistent disk or
# wipe it on every redeploy/restart, so anything saved locally eventually gets
# lost. Cloudinary has a free-forever plan that needs no credit card, gives a
# generous storage + bandwidth allowance every month, and keeps uploaded files
# with no expiry date - so event media survives redeploys and costs nothing to run.
#
# Sign up free at https://cloudinary.com/users/register_free, then copy the
# "Cloud name", "API Key", and "API Secret" from your dashboard into .env
# (see .env.example). Everything below is a no-op (and upload will fail with a
# clear error) until those three env vars are set.
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)
CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "village-portal/events")

# Extension -> media type. Anything not listed here is rejected on upload for safety.
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv"}
ALLOWED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS

# Everything goes to Cloudinary now (photos, videos, and documents alike) -
# just under a different Cloudinary "resource_type" per kind. Simpler to run
# (one provider, one set of API keys) at the cost of sharing Cloudinary's
# single free-tier quota across all media instead of splitting large
# files off onto a second provider. Fine for a small village portal's
# volume; revisit only if the free quota ever becomes a real constraint.


class ApiError(Exception):
    """Lightweight stand-in for FastAPI's HTTPException - raise this from
    inside a view (even mid-loop) and it's turned into a JSON error response."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _classify_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in PHOTO_EXTENSIONS:
        return "photo"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return ""


def _cloud_resource_type(media_type: str) -> str:
    """Maps our own photo/video/document label to Cloudinary's resource_type."""
    if media_type == "photo":
        return "image"
    if media_type == "video":
        return "video"
    return "raw"  # documents (pdf, docx, etc.) upload as "raw" assets


def _media_to_out(media: EventMedia) -> dict:
    """Shapes the DB row into the API response. file_path already holds the
    full Cloudinary secure_url, used as-is."""
    return EventMediaOut(
        id=media.id,
        event_id=media.event_id,
        media_type=media.media_type,
        original_filename=media.original_filename,
        url=media.file_path,
        mime_type=media.mime_type,
        file_size=media.file_size,
        uploaded_at=media.uploaded_at.isoformat() if media.uploaded_at else None,
    ).model_dump()


app = Flask(__name__, static_folder="static", static_url_path="/static", template_folder="templates")

# ===== CORS =====
# Not needed for the server-rendered web pages (browser + server are the same
# origin), but required once a separate client - e.g. the Android/iOS app
# planned for later - starts calling the /api/* endpoints directly from a
# different origin. Comma-separated list of allowed origins, e.g.
# "https://myapp.vercel.app,capacitor://localhost,http://localhost:19006".
# Defaults to "*" (any origin) so nothing breaks before you've picked a
# final app origin - tighten this once you know it.
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
CORS(
    app,
    resources={r"/api/*": {"origins": "*" if _allowed_origins == "*" else [o.strip() for o in _allowed_origins.split(",")]}},
    supports_credentials=_allowed_origins != "*",
)

# Detect whether we're running on Vercel (or set FORCE_HTTPS=1 anywhere else
# served over HTTPS) so cookies are marked Secure automatically instead of
# needing a manual code edit before every deploy.
IS_PRODUCTION = bool(os.getenv("VERCEL")) or os.getenv("FORCE_HTTPS", "").lower() in ("1", "true", "yes")


# ===== STARTUP: create tables and a default admin user =====
# Runs once at import time (module load), mirroring the original create_admin().
def _init_startup():
    init_db()
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        if not admin:
            admin = Admin(username="admin", password_hash=hash_password("admin123"))
            db.add(admin)
            db.commit()
            print("=" * 40)
            print("Admin user created!")
            print("Username: admin")
            print("Password: admin123")
            print("=" * 40)
    finally:
        db.close()


# NOTE: _init_startup() is intentionally NOT called here at import time.
# Vercel's Python build step imports this module just to detect the `app`
# object (you'll see "Running main.py" in build logs), which happens before
# runtime env vars/network access can be relied on. Running DB setup then
# would make deploys fail for reasons that have nothing to do with your
# actual traffic. Instead it runs lazily, once, on the first real request.
_startup_done = False


# ===== DB SESSION PER REQUEST =====

@app.before_request
def open_db_session():
    global _startup_done
    if not _startup_done:
        _init_startup()
        _startup_done = True
    g.db = SessionLocal()


@app.teardown_appcontext
def close_db_session(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return jsonify({"detail": err.detail}), err.status_code


@app.get("/api/health")
def health_check():
    """Simple uptime/deploy-verification endpoint - handy for confirming the
    Vercel deployment and Neon database connection are both working."""
    from database import engine
    db_ok = True
    db_error = None
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as e:
        db_ok = False
        db_error = str(e)
    return jsonify({"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else db_error})


# ===== PUBLIC PAGE =====

@app.get("/")
def index():
    db = g.db
    services = db.query(Service).all()
    events = db.query(Event).all()
    announcements = db.query(Announcement).all()
    complaints = db.query(Complaint).all()
    return render_template(
        "index.html",
        services=services,
        events=events,
        announcements=announcements,
        complaints=complaints,
    )


# ===== ADMIN AUTH =====

@app.get("/admin/login")
def admin_login_page():
    error = request.args.get("error")
    return render_template("admin_login.html", error=error)


@app.post("/admin/login")
def admin_login_submit():
    db = g.db
    username = request.form.get("username")
    password = request.form.get("password")

    admin = db.query(Admin).filter(Admin.username == username).first()

    if admin and verify_password(password, admin.password_hash):
        token = create_access_token(
            data={"sub": admin.username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        response = make_response(redirect(url_for("admin_dashboard")))
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="Lax",
            secure=IS_PRODUCTION,  # auto-True on Vercel (HTTPS); False for local http:// dev
        )
        return response
    else:
        return redirect(url_for("admin_login_page", error="Invalid credentials"))


@app.get("/admin/logout")
def admin_logout():
    response = make_response(redirect(url_for("admin_login_page")))
    response.delete_cookie(COOKIE_NAME)
    return response


# ===== ADMIN DASHBOARD =====

@app.get("/admin/dashboard")
@login_required
def admin_dashboard():
    db = g.db
    services = db.query(Service).all()
    events = db.query(Event).all()
    announcements = db.query(Announcement).all()
    complaints = db.query(Complaint).all()

    stats = {
        "services": len(services),
        "events": len(events),
        "announcements": len(announcements),
        "complaints": len(complaints),
        "pending_complaints": db.query(Complaint).filter(Complaint.status == "Pending").count(),
    }

    return render_template(
        "admin_dashboard.html",
        services=services,
        events=events,
        announcements=announcements,
        complaints=complaints,
        stats=stats,
        current_user=g.current_admin,
    )


# ===== PUBLIC COMPLAINT SUBMISSION (no auth) =====

@app.post("/api/public/complaints")
def public_add_complaint():
    db = g.db
    try:
        payload = PublicComplaintIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    try:
        complaint = Complaint(
            title=payload.title,
            description=payload.description,
            location=payload.location or "",
            status="Pending",
            date=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        db.add(complaint)
        db.commit()
        db.refresh(complaint)
        return jsonify({"success": True, "id": complaint.id, "message": "Complaint submitted successfully!"})
    except Exception as e:
        db.rollback()
        return jsonify({"detail": str(e)}), 400


# ===== SERVICES API (admin only) =====

@app.post("/api/services")
@login_required
def add_service():
    db = g.db
    try:
        payload = ServiceIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    service = Service(**payload.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return jsonify({"success": True, "id": service.id})


@app.get("/api/services/<int:service_id>")
@login_required
def get_service(service_id):
    db = g.db
    service = db.query(Service).get(service_id)
    if not service:
        return jsonify({"detail": "Service not found"}), 404
    return jsonify(ServiceOut.model_validate(service).model_dump())


@app.put("/api/services/<int:service_id>")
@login_required
def update_service(service_id):
    db = g.db
    service = db.query(Service).get(service_id)
    if not service:
        return jsonify({"detail": "Service not found"}), 404
    try:
        payload = ServiceIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    service.title = payload.title
    service.description = payload.description
    service.contact = payload.contact or ""
    service.is_emergency = payload.is_emergency or False
    service.updated_at = datetime.utcnow()
    db.commit()
    return jsonify({"success": True})


@app.delete("/api/services/<int:service_id>")
@login_required
def delete_service(service_id):
    db = g.db
    service = db.query(Service).get(service_id)
    if not service:
        return jsonify({"detail": "Service not found"}), 404
    db.delete(service)
    db.commit()
    return jsonify({"success": True})


# ===== EVENTS API (admin only) =====

@app.post("/api/events")
@login_required
def add_event():
    db = g.db
    try:
        payload = EventIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    event = Event(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return jsonify({"success": True, "id": event.id})


@app.get("/api/events/<int:event_id>")
@login_required
def get_event(event_id):
    db = g.db
    event = db.query(Event).get(event_id)
    if not event:
        return jsonify({"detail": "Event not found"}), 404
    return jsonify(EventOut.model_validate(event).model_dump())


@app.put("/api/events/<int:event_id>")
@login_required
def update_event(event_id):
    db = g.db
    event = db.query(Event).get(event_id)
    if not event:
        return jsonify({"detail": "Event not found"}), 404
    try:
        payload = EventIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    event.title = payload.title
    event.description = payload.description
    event.date = payload.date
    event.location = payload.location or ""
    event.updated_at = datetime.utcnow()
    db.commit()
    return jsonify({"success": True})


@app.delete("/api/events/<int:event_id>")
@login_required
def delete_event(event_id):
    db = g.db
    event = db.query(Event).get(event_id)
    if not event:
        return jsonify({"detail": "Event not found"}), 404
    # Remember each attached file's Cloudinary identity before the DB rows are
    # removed (the DB rows themselves are removed automatically via the
    # cascade="all, delete-orphan" relationship), then delete them from the
    # cloud too so nothing orphaned keeps sitting in the Cloudinary account.
    cloud_assets = [(m.stored_filename, m.cloud_resource_type) for m in event.media]
    db.delete(event)
    db.commit()
    for stored_filename, resource_type in cloud_assets:
        try:
            cloudinary.uploader.destroy(stored_filename, resource_type=resource_type)
        except Exception:
            pass  # best-effort cleanup; DB rows are already gone
    return jsonify({"success": True})


# ===== EVENT MEDIA API: photos / videos / documents attached to an event =====
# Uploading requires admin auth; viewing the list (and the files themselves, via
# their Cloudinary URLs) is public so anyone can browse an event's gallery/documents.

@app.get("/api/events/<int:event_id>/media")
def list_event_media(event_id):
    db = g.db
    event = db.query(Event).get(event_id)
    if not event:
        return jsonify({"detail": "Event not found"}), 404
    return jsonify([_media_to_out(m) for m in event.media])


# Public, no auth required: anyone can download any event's photos/videos/documents.
# Cloudinary's "fl_attachment" delivery flag makes it send back
# Content-Disposition: attachment, so this reliably triggers a real download in
# the browser (instead of opening inline, which is what a plain link would do).
@app.get("/media/<int:media_id>/download")
def download_event_media(media_id):
    db = g.db
    media = db.query(EventMedia).get(media_id)
    if not media:
        return jsonify({"detail": "File not found"}), 404

    download_url, _ = cloudinary_url(
        media.stored_filename,
        resource_type=media.cloud_resource_type,
        flags=f"attachment:{media.original_filename}",
    )
    return redirect(download_url)


@app.post("/api/events/<int:event_id>/media")
@login_required
def upload_event_media(event_id):
    """
    Accepts any number of files in one request (photos, videos, and/or documents
    mixed together) under the "files" form field. Each is streamed straight to
    Cloudinary (free cloud storage) under a unique public_id so nothing is ever
    overwritten, and a matching EventMedia row is created pointing at the
    returned secure_url. There is no cap on how many files an event can
    accumulate, and files are kept indefinitely with no expiry - only
    Cloudinary's free-tier monthly quota applies, which comfortably covers a
    small village portal.
    """
    db = g.db
    event = db.query(Event).get(event_id)
    if not event:
        return jsonify({"detail": "Event not found"}), 404

    files = request.files.getlist("files")
    if not files:
        return jsonify({"detail": "No files provided"}), 400

    saved = []
    try:
        for upload in files:
            media_type = _classify_extension(upload.filename or "")
            if not media_type:
                raise ApiError(
                    400,
                    f"Unsupported file type: {upload.filename}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                )

            if not cloudinary.config().cloud_name:
                raise ApiError(
                    503,
                    "Cloud storage isn't configured yet. Set CLOUDINARY_CLOUD_NAME, "
                    "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in .env (see .env.example).",
                )

            resource_type = _cloud_resource_type(media_type)
            public_id = uuid.uuid4().hex

            # cloudinary.uploader.upload streams the file straight to the
            # cloud; it never touches the app server's own disk. Werkzeug's
            # FileStorage proxies .read() to its underlying stream, so it can
            # be passed directly.
            result = cloudinary.uploader.upload(
                upload,
                folder=f"{CLOUDINARY_FOLDER}/{event_id}",
                public_id=public_id,
                resource_type=resource_type,
                use_filename=False,
                unique_filename=False,
                overwrite=False,
            )

            media = EventMedia(
                event_id=event_id,
                media_type=media_type,
                original_filename=upload.filename,
                stored_filename=result["public_id"],
                file_path=result["secure_url"],
                cloud_resource_type=resource_type,
                mime_type=upload.content_type,
                file_size=result.get("bytes"),
            )

            db.add(media)
            saved.append(media)

        db.commit()
        for media in saved:
            db.refresh(media)
        return jsonify([_media_to_out(m) for m in saved])
    except ApiError as e:
        db.rollback()
        return jsonify({"detail": e.detail}), e.status_code
    except Exception as e:
        db.rollback()
        return jsonify({"detail": str(e)}), 400


@app.delete("/api/events/<int:event_id>/media/<int:media_id>")
@login_required
def delete_event_media(event_id, media_id):
    db = g.db
    media = db.query(EventMedia).filter(EventMedia.id == media_id, EventMedia.event_id == event_id).first()
    if not media:
        return jsonify({"detail": "Media not found"}), 404

    stored_filename = media.stored_filename
    resource_type = media.cloud_resource_type
    db.delete(media)
    db.commit()

    try:
        cloudinary.uploader.destroy(stored_filename, resource_type=resource_type)
    except Exception:
        pass  # DB row is already gone; a stray cloud file isn't worth failing the request over

    return jsonify({"success": True})


# ===== ANNOUNCEMENTS API (admin only) =====

@app.post("/api/announcements")
@login_required
def add_announcement():
    db = g.db
    try:
        payload = AnnouncementIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    announcement = Announcement(**payload.model_dump())
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return jsonify({"success": True, "id": announcement.id})


@app.get("/api/announcements/<int:announcement_id>")
@login_required
def get_announcement(announcement_id):
    db = g.db
    announcement = db.query(Announcement).get(announcement_id)
    if not announcement:
        return jsonify({"detail": "Announcement not found"}), 404
    return jsonify(AnnouncementOut.model_validate(announcement).model_dump())


@app.put("/api/announcements/<int:announcement_id>")
@login_required
def update_announcement(announcement_id):
    db = g.db
    announcement = db.query(Announcement).get(announcement_id)
    if not announcement:
        return jsonify({"detail": "Announcement not found"}), 404
    try:
        payload = AnnouncementIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    announcement.title = payload.title
    announcement.content = payload.content
    announcement.date = payload.date
    announcement.is_important = payload.is_important or False
    announcement.updated_at = datetime.utcnow()
    db.commit()
    return jsonify({"success": True})


@app.delete("/api/announcements/<int:announcement_id>")
@login_required
def delete_announcement(announcement_id):
    db = g.db
    announcement = db.query(Announcement).get(announcement_id)
    if not announcement:
        return jsonify({"detail": "Announcement not found"}), 404
    db.delete(announcement)
    db.commit()
    return jsonify({"success": True})


# ===== COMPLAINTS API (admin only) =====

@app.post("/api/complaints")
@login_required
def add_complaint():
    db = g.db
    try:
        payload = ComplaintIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    complaint = Complaint(
        title=payload.title,
        description=payload.description,
        location=payload.location or "",
        status=payload.status or "Pending",
        date=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return jsonify({"success": True, "id": complaint.id})


@app.get("/api/complaints/<int:complaint_id>")
@login_required
def get_complaint(complaint_id):
    db = g.db
    complaint = db.query(Complaint).get(complaint_id)
    if not complaint:
        return jsonify({"detail": "Complaint not found"}), 404
    return jsonify(ComplaintOut.model_validate(complaint).model_dump())


@app.put("/api/complaints/<int:complaint_id>")
@login_required
def update_complaint(complaint_id):
    db = g.db
    complaint = db.query(Complaint).get(complaint_id)
    if not complaint:
        return jsonify({"detail": "Complaint not found"}), 404
    try:
        payload = ComplaintIn.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400
    complaint.title = payload.title
    complaint.description = payload.description
    complaint.location = payload.location or ""
    complaint.status = payload.status or complaint.status
    complaint.updated_at = datetime.utcnow()
    db.commit()
    return jsonify({"success": True})


@app.delete("/api/complaints/<int:complaint_id>")
@login_required
def delete_complaint(complaint_id):
    db = g.db
    complaint = db.query(Complaint).get(complaint_id)
    if not complaint:
        return jsonify({"detail": "Complaint not found"}), 404
    db.delete(complaint)
    db.commit()
    return jsonify({"success": True})


if __name__ == "__main__":
    print()
    print("Starting Village Information Portal (Flask)...")
    print("Visit: http://localhost:8000")
    print("Admin Login: http://localhost:8000/admin/login")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8000, debug=True)
