from functools import wraps

from flask import abort, redirect, request, url_for
from flask_login import current_user

from .extensions import db
from .models import Class, Session, Student


def _is_user():
    return current_user.is_authenticated and current_user.kind == "user"


def login_required_user(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        if current_user.kind != "user":
            abort(403)
        return fn(*a, **kw)
    return w


def admin_required(fn):
    @wraps(fn)
    @login_required_user
    def w(*a, **kw):
        if not current_user.is_admin:
            abort(403)
        return fn(*a, **kw)
    return w


def platform_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not current_user.is_authenticated:
            return redirect(url_for("platform.login"))
        if current_user.kind != "platform":
            abort(403)
        return fn(*a, **kw)
    return w


def get_class_or_404(class_id) -> Class:
    """Tenant and ownership check. Other orgs' or other tutors' classes look like 404."""
    c = db.session.get(Class, class_id)
    if (c is None or c.organisation_id != current_user.organisation_id
            or (not current_user.is_admin and c.tutor_id != current_user.id)):
        abort(404)
    return c


def get_session_or_404(session_id) -> Session:
    s = db.session.get(Session, session_id)
    if s is None:
        abort(404)
    get_class_or_404(s.class_id)
    return s


def get_student_or_404(student_id) -> Student:
    st = db.session.get(Student, student_id)
    if st is None or st.organisation_id != current_user.organisation_id:
        abort(404)
    return st
