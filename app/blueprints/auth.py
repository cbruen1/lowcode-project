from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from ..extensions import db, limiter
from ..models import User
from ..security import _is_user

bp = Blueprint("auth", __name__)


def _safe_next(target, default):
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return default


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("platform.index" if current_user.kind == "platform" else "tutor.classes"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: __import__("flask").current_app.config["LOGIN_RATE"], methods=["POST"])
def login():
    if _is_user():
        return redirect(url_for("tutor.classes"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            login_user(user)
            return redirect(_safe_next(request.args.get("next"), url_for("tutor.classes")))
        error = "That email and password don't match."
    return render_template("login.html", error=error, platform=False)


@bp.route("/logout", methods=["POST"])
def logout():
    was_platform = current_user.is_authenticated and current_user.kind == "platform"
    logout_user()
    return redirect(url_for("platform.login" if was_platform else "auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        cur, new, again = (request.form.get(k, "") for k in ("current", "new", "again"))
        if not current_user.check_password(cur):
            error = "Your current password is not correct."
        elif len(new) < 10:
            error = "Choose a password of at least 10 characters."
        elif new != again:
            error = "The two new passwords don't match."
        elif new == cur:
            error = "Choose a different password from the current one."
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash("Password changed.", "ok")
            return redirect(url_for("platform.index" if current_user.kind == "platform" else "tutor.classes"))
    return render_template("change_password.html", error=error)
