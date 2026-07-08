"""
Pydantic schemas used for request validation and response shaping.
FastAPI uses these in place of Flask's manual request.json handling.
"""
from typing import Optional
from pydantic import BaseModel, Field


# ===== AUTH =====

class LoginForm(BaseModel):
    username: str
    password: str


# ===== SERVICE =====

class ServiceIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    contact: Optional[str] = ""
    is_emergency: Optional[bool] = False


class ServiceOut(BaseModel):
    id: int
    title: str
    description: str
    contact: Optional[str]
    is_emergency: bool

    class Config:
        from_attributes = True


# ===== EVENT =====

class EventIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    date: str
    location: Optional[str] = ""


class EventOut(BaseModel):
    id: int
    title: str
    description: str
    date: str
    location: Optional[str]

    class Config:
        from_attributes = True


# ===== EVENT MEDIA (photos / videos / documents attached to an event) =====

class EventMediaOut(BaseModel):
    id: int
    event_id: int
    media_type: str          # "photo" | "video" | "document"
    original_filename: str
    url: str                 # public URL the file can be viewed/downloaded at
    mime_type: Optional[str]
    file_size: Optional[int]
    uploaded_at: Optional[str]

    class Config:
        from_attributes = True


# ===== ANNOUNCEMENT =====

class AnnouncementIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    date: str
    is_important: Optional[bool] = False


class AnnouncementOut(BaseModel):
    id: int
    title: str
    content: str
    date: str
    is_important: bool

    class Config:
        from_attributes = True


# ===== COMPLAINT =====

class ComplaintIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    location: Optional[str] = ""
    status: Optional[str] = "Pending"


class PublicComplaintIn(BaseModel):
    """Schema for the public, unauthenticated complaint submission endpoint."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    location: Optional[str] = ""


class ComplaintOut(BaseModel):
    id: int
    title: str
    description: str
    location: Optional[str]
    status: str
    date: str

    class Config:
        from_attributes = True


class SuccessOut(BaseModel):
    success: bool
    id: Optional[int] = None
    message: Optional[str] = None
