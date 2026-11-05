import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import Index, UniqueConstraint, text

from .extensions import db, login_manager
from .timeutil import now_utc, utc_to_local

_ph = PasswordHasher()


class PasswordMixin:
    def set_password(self, pw: str):
        self.password_hash = _ph.hash(pw)

    def check_password(self, pw: str) -> bool:
        try:
            return _ph.verify(self.password_hash, pw)
        except (VerifyMismatchError, InvalidHashError):
            return False


def new_temp_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


class Organisation(db.Model):
    __tablename__ = "organisation"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    time_zone = db.Column(db.String(64), nullable=False, default="Europe/Dublin")
    privacy_contact_email = db.Column(db.String(255), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_utc)

    users = db.relationship("User", backref="organisation", lazy="dynamic")


class User(UserMixin, PasswordMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisation.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # admin | tutor
    active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_utc)

    __table_args__ = (
        db.CheckConstraint("role in ('admin','tutor')", name="ck_user_role"),
        Index("uq_one_admin_per_org", "organisation_id", unique=True, sqlite_where=text("role = 'admin'")),
    )

    kind = "user"

    def get_id(self):
        return f"u:{self.id}"

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_active(self):
        return self.active and self.organisation.active


class PlatformOwner(UserMixin, PasswordMixin, db.Model):
    __tablename__ = "platform_owner"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)

    kind = "platform"
    is_admin = False

    def get_id(self):
        return f"p:{self.id}"


@login_manager.user_loader
def load_user(uid):
    try:
        kind, _, raw = uid.partition(":")
        ident = int(raw)
    except ValueError:
        return None
    if kind == "u":
        return db.session.get(User, ident)
    if kind == "p":
        return db.session.get(PlatformOwner, ident)
    return None


class Student(db.Model):
    __tablename__ = "student"
    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisation.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_utc)

    __table_args__ = (Index("uq_student_org_email", "organisation_id", "email", unique=True),)


class Class(db.Model):
    __tablename__ = "class"
    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisation.id"), nullable=False, index=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    weekday = db.Column(db.Integer, nullable=False)  # 0=Mon
    start_time = db.Column(db.Time, nullable=False)  # local
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    first_date = db.Column(db.Date, nullable=False)
    ended_on = db.Column(db.Date)
    late_after_minutes = db.Column(db.Integer, nullable=False, default=10)
    qr_checkin_enabled = db.Column(db.Boolean, nullable=False, default=False)
    checkin_opens_before_minutes = db.Column(db.Integer, nullable=False, default=15)
    checkin_closes_after_minutes = db.Column(db.Integer, nullable=False, default=30)
    created_at = db.Column(db.DateTime, nullable=False, default=now_utc)

    organisation = db.relationship("Organisation")
    tutor = db.relationship("User")
    enrolments = db.relationship("Enrolment", backref="class_", cascade="all, delete-orphan")
    sessions = db.relationship("Session", backref="class_", cascade="all, delete-orphan",
                               order_by="Session.date")

    __table_args__ = (db.CheckConstraint("weekday between 0 and 6", name="ck_class_weekday"),)


class Enrolment(db.Model):
    __tablename__ = "enrolment"
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    student = db.relationship("Student")
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrolment"),)


class Session(db.Model):
    __tablename__ = "session"
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)  # local date
    starts_at = db.Column(db.DateTime, nullable=False)  # naive UTC
    status = db.Column(db.String(12), nullable=False, default="scheduled")  # scheduled|cancelled
    qr_token = db.Column(db.String(64), unique=True, nullable=False,
                         default=lambda: secrets.token_urlsafe(24))

    attendance = db.relationship("Attendance", backref="session", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("class_id", "date", name="uq_session_class_date"),)

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.class_.duration_minutes)

    def local_start(self):
        return utc_to_local(self.starts_at, self.class_.organisation.time_zone)


class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=True, index=True)
    submitted_name = db.Column(db.String(200))
    submitted_email = db.Column(db.String(255))
    status = db.Column(db.String(10), nullable=False)  # present|late|absent
    source = db.Column(db.String(10), nullable=False, default="tutor")  # tutor|self
    enrolled = db.Column(db.Boolean, nullable=False, default=True)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    recorded_at = db.Column(db.DateTime, nullable=False, default=now_utc)

    student = db.relationship("Student")

    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_attendance_student"),
        Index("uq_attendance_email", "session_id", "submitted_email", unique=True,
              sqlite_where=text("submitted_email IS NOT NULL")),
        db.CheckConstraint("status in ('present','late','absent')", name="ck_att_status"),
    )


class AuditLog(db.Model):
    """Holds no personal data: only ids, action names and status changes."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisation.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    platform_owner_id = db.Column(db.Integer, db.ForeignKey("platform_owner.id"))
    action = db.Column(db.String(60), nullable=False)
    class_id = db.Column(db.Integer)
    session_id = db.Column(db.Integer)
    attendance_id = db.Column(db.Integer)
    before = db.Column(db.Text)
    after = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, nullable=False, default=now_utc, index=True)

    user = db.relationship("User")
