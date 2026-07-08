"""
Cookie + JWT based authentication, replacing Flask-Login.

Flask-Login normally keeps a server-side session cookie tied to a
user_loader callback. Here we instead issue a signed JWT, store it in an
HttpOnly cookie, and verify it on every protected request via the
`login_required` decorator below. This keeps the "login -> redirect ->
protected pages" flow working the same way Flask-Login's @login_required did.
"""
import os
from functools import wraps
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from flask import request, redirect, url_for, g
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import Admin

# ===== CONFIG =====
# In production, set SECRET_KEY via an environment variable - never commit a real secret.
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 hours, similar to a typical Flask session lifetime
COOKIE_NAME = "access_token"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _admin_from_cookie(db) -> Optional[Admin]:
    """Reads the JWT from the cookie, validates it, and loads the matching
    Admin row. Returns None if there's no valid session."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    return db.query(Admin).filter(Admin.username == username).first()


def get_current_admin_optional(db) -> Optional[Admin]:
    """Like the decorator below, but for use inside a view that wants to
    render differently for logged-in vs anonymous users without forcing a
    login (never redirects)."""
    return _admin_from_cookie(db)


def login_required(view_func):
    """
    Decorator for protected routes - the Flask equivalent of Flask-Login's
    @login_required. Reads the JWT cookie, validates it, and stashes the
    matching Admin on `g.current_admin`. Redirects to /admin/login if the
    cookie is missing/invalid, mirroring the original app's browser-friendly
    behavior (used for both page routes and the JSON /api/* admin routes).
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        admin = _admin_from_cookie(g.db)
        if admin is None:
            return redirect(url_for("admin_login_page"))
        g.current_admin = admin
        return view_func(*args, **kwargs)
    return wrapped
