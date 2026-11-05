import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    DATABASE_PATH = os.environ.get("DATABASE_PATH") or str(BASE_DIR / "instance" / "attendance.db")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
    SESSION_COOKIE_NAME = "att_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") != "0"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
    WTF_CSRF_TIME_LIMIT = None
    RATELIMIT_STORAGE_URI = "memory://"
    LOGIN_RATE = os.environ.get("LOGIN_RATE", "10 per minute")
    CHECKIN_RATE = os.environ.get("CHECKIN_RATE", "60 per minute")
    SESSIONS_AHEAD_WEEKS = 12
    MAX_CONTENT_LENGTH = 1024 * 1024
    PRIVACY_NOTICE = os.environ.get("PRIVACY_NOTICE") or (
        "Your name and email are recorded to mark your attendance for this class. "
        "They are used only by your organisation and can be deleted on request."
    )


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SERVER_NAME = None
