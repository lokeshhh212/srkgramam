"""
Database engine, session, and ORM models for the Village Portal.
Uses SQLAlchemy 2.0 style with SQLite by default (swap DATABASE_URL for
Postgres/Neon in production - e.g. when deploying to Vercel, which has no
persistent disk so SQLite cannot be used there).

Framework-agnostic - main.py (Flask) opens a SessionLocal() per request
via g.db and closes it in a teardown handler.
"""
import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./village_portal.db")

# Neon (and some other providers/older guides) hand out URLs starting with
# "postgres://", but SQLAlchemy 1.4+/2.0 requires the "postgresql://" scheme
# and the psycopg2 driver needs to be named explicitly. Normalize both here so
# whatever string is pasted into DATABASE_URL just works.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_SERVERLESS = bool(os.getenv("VERCEL"))  # Vercel sets this env var automatically

connect_args = {}
engine_kwargs = {}

if IS_SQLITE:
    connect_args = {"check_same_thread": False}
else:
    # Neon requires SSL; add it if the URL doesn't already specify sslmode.
    if "sslmode" not in DATABASE_URL:
        connect_args["sslmode"] = "require"
    if IS_SERVERLESS:
        # Serverless functions are short-lived and spin up many parallel
        # instances, so a traditional connection pool held in memory does
        # more harm than good (stale/orphaned connections pile up on the
        # database side). NullPool opens a fresh connection per request and
        # closes it right after - pairs well with Neon's own pooler
        # (use the "-pooler" host in your connection string on Vercel).
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ===== MODELS =====

class Admin(Base):
    __tablename__ = "admin"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Service(Base):
    __tablename__ = "service"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    contact = Column(String(50), nullable=True)
    is_emergency = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Event(Base):
    __tablename__ = "event"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    date = Column(String(50), nullable=False)
    location = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # An event can have any number of photos/videos/documents attached.
    # cascade="all, delete-orphan" means deleting an Event also removes its
    # EventMedia rows (the actual files on disk are cleaned up in main.py).
    media = relationship(
        "EventMedia",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventMedia.uploaded_at",
    )


class EventMedia(Base):
    """
    One row per uploaded file (photo, video, or document) attached to an event.
    Files themselves are stored on Cloudinary (a free cloud media host) instead of
    the app server's local disk. Why: most free/no-cost deployment platforms
    (Render/Railway free tiers, etc.) wipe local disk on every redeploy or restart,
    so anything saved to disk eventually disappears. Cloudinary's free forever
    plan needs no credit card, has a generous storage/bandwidth allowance, and
    keeps files with no expiry, so media survives redeploys and doesn't cost
    anything or eat the server's own disk space.
    """
    __tablename__ = "event_media"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("event.id", ondelete="CASCADE"), nullable=False, index=True)

    media_type = Column(String(20), nullable=False)  # "photo" | "video" | "document" (our own label)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)  # Cloudinary public_id - needed to delete the file later
    file_path = Column(String(500), nullable=False)  # Cloudinary secure_url
    cloud_resource_type = Column(String(20), nullable=False, default="image")  # Cloudinary's own type: "image" | "video" | "raw"
    mime_type = Column(String(100), nullable=True)
    file_size = Column(BigInteger, nullable=True)  # bytes

    uploaded_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="media")


class Announcement(Base):
    __tablename__ = "announcement"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    date = Column(String(50), nullable=False)
    is_important = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Complaint(Base):
    __tablename__ = "complaint"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(200), nullable=True)
    status = Column(String(50), default="Pending")
    date = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
