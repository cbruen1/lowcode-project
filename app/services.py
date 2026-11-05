import csv
import io
import json
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy import func

from .extensions import db
from .models import (Attendance, AuditLog, Class, Enrolment, Organisation, Session, Student,
                     User, new_temp_password)
from .timeutil import local_to_utc, now_utc, occurrence_dates, today_local, utc_to_local

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATUSES = ("present", "late", "absent")


class ServiceError(Exception):
    pass


def norm_email(e: str) -> str:
    return (e or "").strip().lower()


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match(e or "")) and len(e) <= 255


def valid_tz(tz: str) -> bool:
    return tz in available_timezones()


# ---------- audit ----------
def audit(org_id, action, actor=None, class_id=None, session_id=None, attendance_id=None,
          before=None, after=None):
    """Audit rows carry ids and status words only, never names or emails."""
    entry = AuditLog(organisation_id=org_id, action=action, class_id=class_id,
                     session_id=session_id, attendance_id=attendance_id,
                     before=json.dumps(before) if before is not None else None,
                     after=json.dumps(after) if after is not None else None)
    if actor is not None:
        if actor.kind == "user":
            entry.user_id = actor.id
        else:
            entry.platform_owner_id = actor.id
    db.session.add(entry)
    return entry


# ---------- sessions ----------
def _horizon(cls, weeks):
    tz = cls.organisation.time_zone
    end = today_local(tz) + timedelta(weeks=weeks)
    if cls.ended_on:
        end = min(end, cls.ended_on)
    return end


def ensure_sessions(cls: Class, weeks: int = 12) -> int:
    """Create missing weekly sessions from first_date up to the rolling horizon."""
    tz = cls.organisation.time_zone
    existing = {d for (d,) in db.session.query(Session.date).filter_by(class_id=cls.id)}
    # History is only backfilled for a brand-new class. Afterwards we generate from today,
    # so a weekday change never recreates past sessions on the new weekday.
    start = cls.first_date if not existing else max(cls.first_date, today_local(tz))
    created = 0
    for d in occurrence_dates(cls.first_date, cls.weekday, start, _horizon(cls, weeks)):
        if d in existing:
            continue
        db.session.add(Session(class_id=cls.id, date=d,
                               starts_at=local_to_utc(d, cls.start_time, tz)))
        created += 1
    return created


def top_up_all(weeks: int = 12) -> int:
    n = 0
    for cls in Class.query.join(Organisation).filter(Organisation.active.is_(True)):
        if cls.ended_on and cls.ended_on < today_local(cls.organisation.time_zone):
            continue
        n += ensure_sessions(cls, weeks)
    db.session.commit()
    return n


def reschedule_future(cls: Class, old_weekday: int):
    """After a schedule change, touch only future sessions that have no attendance."""
    tz = cls.organisation.time_zone
    today = today_local(tz)
    future = Session.query.filter(Session.class_id == cls.id, Session.date >= today).all()
    for s in future:
        if s.attendance:
            continue
        if cls.weekday == old_weekday:
            s.starts_at = local_to_utc(s.date, cls.start_time, tz)
        else:
            db.session.delete(s)
    db.session.flush()
    ensure_sessions(cls)


def end_class(cls: Class, actor):
    tz = cls.organisation.time_zone
    today = today_local(tz)
    cls.ended_on = today
    for s in Session.query.filter(Session.class_id == cls.id, Session.date > today).all():
        if not s.attendance:
            db.session.delete(s)
    audit(cls.organisation_id, "class.end", actor, class_id=cls.id)


def set_session_status(s: Session, status: str, actor):
    if status not in ("scheduled", "cancelled"):
        raise ServiceError("Invalid status")
    before = s.status
    s.status = status
    audit(s.class_.organisation_id, f"session.{status}", actor, class_id=s.class_id,
          session_id=s.id, before={"status": before}, after={"status": status})


# ---------- attendance ----------
def _check_recordable(s: Session):
    if s.status == "cancelled":
        raise ServiceError("This session is cancelled.")
    tz = s.class_.organisation.time_zone
    if s.date > today_local(tz):
        raise ServiceError("This session is in the future and cannot be recorded yet.")


def record(s: Session, student: Student, status: str, actor):
    """status in present/late/absent, or 'none' to clear back to not recorded."""
    _check_recordable(s)
    if student.organisation_id != s.class_.organisation_id:
        raise ServiceError("Student not found.")
    row = Attendance.query.filter_by(session_id=s.id, student_id=student.id).first()
    org = s.class_.organisation_id
    if status == "none":
        if row:
            audit(org, "attendance.clear", actor, s.class_id, s.id, row.id,
                  before={"status": row.status}, after={"status": None})
            db.session.delete(row)
        return None
    if status not in STATUSES:
        raise ServiceError("Invalid status")
    enrolled = Enrolment.query.filter_by(class_id=s.class_id, student_id=student.id).first()
    if not enrolled:
        db.session.add(Enrolment(class_id=s.class_id, student_id=student.id))
    if row:
        if row.status == status:
            return row
        before = {"status": row.status}
        row.status = status
        row.source, row.recorded_by_user_id, row.recorded_at = "tutor", actor.id, now_utc()
        row.enrolled = True
        audit(org, "attendance.update", actor, s.class_id, s.id, row.id, before, {"status": status})
        return row
    row = Attendance(session_id=s.id, student_id=student.id, status=status, source="tutor",
                     enrolled=True, recorded_by_user_id=actor.id)
    db.session.add(row)
    db.session.flush()
    audit(org, "attendance.create", actor, s.class_id, s.id, row.id, None, {"status": status})
    return row


def mark_all_present(s: Session, actor) -> int:
    _check_recordable(s)
    done = {a.student_id for a in s.attendance if a.student_id}
    n = 0
    for e in s.class_.enrolments:
        if e.student_id not in done:
            record(s, e.student, "present", actor)
            n += 1
    return n


# ---------- QR check-in ----------
def checkin_window(s: Session):
    c = s.class_
    return (s.starts_at - timedelta(minutes=c.checkin_opens_before_minutes),
            s.starts_at + timedelta(minutes=c.checkin_closes_after_minutes))


def checkin_state(s: Session) -> str:
    """open | not_open | closed | cancelled | disabled"""
    if not s.class_.qr_checkin_enabled or not s.class_.organisation.active:
        return "disabled"
    if s.status == "cancelled":
        return "cancelled"
    opens, closes = checkin_window(s)
    now = now_utc()
    if now < opens:
        return "not_open"
    if now > closes:
        return "closed"
    return "open"


def self_checkin(s: Session, name: str, email: str):
    state = checkin_state(s)
    if state != "open":
        raise ServiceError(state)
    name = (name or "").strip()
    email = norm_email(email)
    if not name or len(name) > 200:
        raise ServiceError("invalid_name")
    if not valid_email(email):
        raise ServiceError("invalid_email")
    c = s.class_
    student = Student.query.filter_by(organisation_id=c.organisation_id, email=email).first()
    if student and Attendance.query.filter_by(session_id=s.id, student_id=student.id).first():
        raise ServiceError("duplicate")
    if Attendance.query.filter(Attendance.session_id == s.id,
                               Attendance.submitted_email == email).first():
        raise ServiceError("duplicate")
    late = now_utc() > s.starts_at + timedelta(minutes=c.late_after_minutes)
    enrolled = bool(student and Enrolment.query.filter_by(class_id=c.id, student_id=student.id).first())
    row = Attendance(session_id=s.id, student_id=student.id if student else None,
                     submitted_name=name, submitted_email=email,
                     status="late" if late else "present", source="self", enrolled=enrolled)
    db.session.add(row)
    db.session.flush()
    audit(c.organisation_id, "attendance.self_checkin", None, c.id, s.id, row.id, None,
          {"status": row.status, "enrolled": enrolled})
    return row


def resolve_unmatched(att: Attendance, actor):
    """Tutor accepts an unmatched/unenrolled self check-in: create or link the student and enrol."""
    s = att.session
    c = s.class_
    student = att.student
    if student is None:
        student = Student.query.filter_by(organisation_id=c.organisation_id,
                                          email=att.submitted_email).first()
    if student is None:
        student = Student(organisation_id=c.organisation_id, name=att.submitted_name,
                          email=att.submitted_email)
        db.session.add(student)
        db.session.flush()
    att.student_id = student.id
    if not Enrolment.query.filter_by(class_id=c.id, student_id=student.id).first():
        db.session.add(Enrolment(class_id=c.id, student_id=student.id))
    att.enrolled = True
    audit(c.organisation_id, "attendance.resolve", actor, c.id, s.id, att.id,
          {"enrolled": False}, {"enrolled": True})


# ---------- students ----------
def create_student(org_id, name, email) -> tuple[Student, bool]:
    name, email = (name or "").strip(), norm_email(email)
    if not name or len(name) > 200:
        raise ServiceError("Enter the student's name.")
    if not valid_email(email):
        raise ServiceError("Enter a valid email address.")
    existing = Student.query.filter_by(organisation_id=org_id, email=email).first()
    if existing:
        return existing, False
    st = Student(organisation_id=org_id, name=name, email=email)
    db.session.add(st)
    db.session.flush()
    return st, True


def enrol(cls: Class, student: Student) -> bool:
    if student.organisation_id != cls.organisation_id:
        raise ServiceError("Student not found.")
    if Enrolment.query.filter_by(class_id=cls.id, student_id=student.id).first():
        return False
    db.session.add(Enrolment(class_id=cls.id, student_id=student.id))
    return True


def unenrol(cls: Class, student: Student):
    Enrolment.query.filter_by(class_id=cls.id, student_id=student.id).delete()


def delete_student_data(student: Student, actor):
    """GDPR erasure: student, their attendance (incl. unmatched self check-ins by email),
    and enrolments. Audit rows hold no personal data so they remain."""
    org = student.organisation_id
    ids = [a.id for a in Attendance.query.filter_by(student_id=student.id)]
    Attendance.query.filter_by(student_id=student.id).delete()
    sess_ids = [s.id for s in Session.query.join(Class).filter(Class.organisation_id == org)]
    if sess_ids:
        Attendance.query.filter(Attendance.session_id.in_(sess_ids),
                                func.lower(Attendance.submitted_email) == student.email).delete(
            synchronize_session=False)
    Enrolment.query.filter_by(student_id=student.id).delete()
    db.session.delete(student)
    audit(org, "student.delete", actor, before={"attendance_rows_removed": len(ids)})


# ---------- CSV import ----------
def parse_csv(text: str):
    """Return list of dicts: name, email, status (new|existing|invalid|duplicate), error."""
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    out, seen = [], set()
    for i, r in enumerate(rows):
        if not r or not any(c.strip() for c in r):
            continue
        name = r[0].strip() if len(r) > 0 else ""
        email = norm_email(r[1]) if len(r) > 1 else ""
        if i == 0 and name.lower() in ("name", "full name") and email in ("email", "e-mail", "email address"):
            continue
        item = {"line": i + 1, "name": name, "email": email, "status": "new", "error": ""}
        if not name:
            item.update(status="invalid", error="Missing name")
        elif not valid_email(email):
            item.update(status="invalid", error="Invalid email")
        elif email in seen:
            item.update(status="duplicate", error="Repeated in file")
        seen.add(email)
        out.append(item)
    return out


def preview_import(org_id, rows):
    existing = {e for (e,) in db.session.query(Student.email).filter_by(organisation_id=org_id)}
    for r in rows:
        if r["status"] == "new" and r["email"] in existing:
            r["status"] = "existing"
    return rows


def apply_import(org_id, rows, cls: Class | None, actor):
    created = linked = 0
    for r in preview_import(org_id, rows):
        if r["status"] not in ("new", "existing"):
            continue
        st, was_new = create_student(org_id, r["name"], r["email"])
        created += was_new
        linked += not was_new
        if cls is not None:
            enrol(cls, st)
    audit(org_id, "students.import", actor, class_id=cls.id if cls else None,
          after={"created": created, "linked": linked})
    return created, linked


# ---------- organisations & users ----------
def create_user(org: Organisation, name, email, role="tutor"):
    name, email = (name or "").strip(), norm_email(email)
    if not name:
        raise ServiceError("Enter a name.")
    if not valid_email(email):
        raise ServiceError("Enter a valid email address.")
    if User.query.filter(func.lower(User.email) == email).first():
        raise ServiceError("That email is already in use.")
    pw = new_temp_password()
    u = User(organisation_id=org.id, name=name, email=email, role=role, must_change_password=True)
    u.set_password(pw)
    db.session.add(u)
    db.session.flush()
    return u, pw


def create_organisation(name, tz, privacy_email, admin_name, admin_email, actor=None):
    name = (name or "").strip()
    if not name:
        raise ServiceError("Enter the organisation name.")
    if not valid_tz(tz):
        raise ServiceError("Choose a valid time zone.")
    privacy_email = norm_email(privacy_email)
    if privacy_email and not valid_email(privacy_email):
        raise ServiceError("Enter a valid privacy contact email.")
    org = Organisation(name=name, time_zone=tz, privacy_contact_email=privacy_email)
    db.session.add(org)
    db.session.flush()
    admin, pw = create_user(org, admin_name, admin_email, "admin")
    audit(org.id, "org.create", actor)
    return org, admin, pw


def update_organisation(org: Organisation, name, tz, privacy_email, active, actor):
    if not (name or "").strip():
        raise ServiceError("Enter the organisation name.")
    if not valid_tz(tz):
        raise ServiceError("Choose a valid time zone.")
    privacy_email = norm_email(privacy_email)
    if privacy_email and not valid_email(privacy_email):
        raise ServiceError("Enter a valid privacy contact email.")
    org.name, org.time_zone, org.privacy_contact_email, org.active = name.strip(), tz, privacy_email, active
    audit(org.id, "org.update", actor)


def replace_admin(org: Organisation, name, email, actor):
    old = User.query.filter_by(organisation_id=org.id, role="admin").first()
    if old:
        old.role = "tutor"
        old.active = False
        db.session.flush()
    admin, pw = create_user(org, name, email, "admin")
    audit(org.id, "org.replace_admin", actor)
    return admin, pw


def delete_organisation(org: Organisation):
    oid = org.id
    sess_ids = [s.id for s in Session.query.join(Class).filter(Class.organisation_id == oid)]
    if sess_ids:
        Attendance.query.filter(Attendance.session_id.in_(sess_ids)).delete(synchronize_session=False)
        Session.query.filter(Session.id.in_(sess_ids)).delete(synchronize_session=False)
    class_ids = [c.id for c in Class.query.filter_by(organisation_id=oid)]
    if class_ids:
        Enrolment.query.filter(Enrolment.class_id.in_(class_ids)).delete(synchronize_session=False)
    Class.query.filter_by(organisation_id=oid).delete()
    Student.query.filter_by(organisation_id=oid).delete()
    AuditLog.query.filter_by(organisation_id=oid).delete()
    User.query.filter_by(organisation_id=oid).delete()
    db.session.delete(org)
