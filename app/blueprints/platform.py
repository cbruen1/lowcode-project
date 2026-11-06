from zoneinfo import available_timezones

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user
from sqlalchemy import func

from ..extensions import db, limiter
from ..models import Class, Organisation, PlatformOwner, Student, User, new_temp_password
from ..security import platform_required
from .. import services

bp = Blueprint("platform", __name__, url_prefix="/platform")


def _tzs():
    common = ["Europe/Dublin", "Europe/London", "Europe/Paris", "Europe/Berlin", "America/New_York"]
    return common + sorted(t for t in available_timezones() if t not in common and "/" in t
                           and not t.startswith(("Etc/", "posix", "right")))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: __import__("flask").current_app.config["LOGIN_RATE"], methods=["POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        owner = PlatformOwner.query.filter(func.lower(PlatformOwner.email) == email).first()
        if owner and owner.check_password(request.form.get("password", "")):
            login_user(owner)
            return redirect(url_for("platform.index"))
        error = "That email and password don't match."
    return render_template("login.html", error=error, platform=True)


def _org_counts(org):
    return {
        "tutors": User.query.filter_by(organisation_id=org.id, role="tutor", active=True).count(),
        "classes": Class.query.filter_by(organisation_id=org.id).count(),
        "students": Student.query.filter_by(organisation_id=org.id).count(),
    }


@bp.route("/")
@platform_required
def index():
    orgs = Organisation.query.order_by(Organisation.name).all()
    rows = [(o, _org_counts(o), User.query.filter_by(organisation_id=o.id, role="admin").first()) for o in orgs]
    return render_template("platform_orgs.html", rows=rows)


def _show_temp(org, user, pw, title):
    return render_template("temp_password.html", org=org, account=user, password=pw, title=title,
                           back=url_for("platform.edit_org", org_id=org.id))


@bp.route("/orgs/new", methods=["GET", "POST"])
@platform_required
def new_org():
    error, f = None, request.form
    if request.method == "POST":
        try:
            org, admin, pw = services.create_organisation(
                f.get("name"), f.get("time_zone", "Europe/Dublin"), f.get("privacy_contact_email"),
                f.get("admin_name"), f.get("admin_email"), current_user)
            db.session.commit()
            return _show_temp(org, admin, pw, "Organisation created")
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    return render_template("platform_org_form.html", org=None, admin=None, error=error, tzs=_tzs(), f=f)


def _get_org(org_id):
    org = db.session.get(Organisation, org_id)
    if org is None:
        abort(404)
    return org


@bp.route("/orgs/<int:org_id>", methods=["GET", "POST"])
@platform_required
def edit_org(org_id):
    org, error, f = _get_org(org_id), None, request.form
    admin = User.query.filter_by(organisation_id=org.id, role="admin").first()
    if request.method == "POST":
        try:
            services.update_organisation(org, f.get("name"), f.get("time_zone"),
                                         f.get("privacy_contact_email"), f.get("active") == "1", current_user)
            if admin and f.get("admin_name", "").strip():
                admin.name = f["admin_name"].strip()
                new_email = services.norm_email(f.get("admin_email"))
                if new_email != admin.email:
                    if not services.valid_email(new_email):
                        raise services.ServiceError("Enter a valid admin email address.")
                    if User.query.filter(func.lower(User.email) == new_email, User.id != admin.id).first():
                        raise services.ServiceError("That email is already in use.")
                    admin.email = new_email
            db.session.commit()
            flash("Organisation saved.", "ok")
            return redirect(url_for("platform.edit_org", org_id=org.id))
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    return render_template("platform_org_form.html", org=org, admin=admin, error=error, tzs=_tzs(),
                           f=f, counts=_org_counts(org))


@bp.route("/orgs/<int:org_id>/reset-admin", methods=["POST"])
@platform_required
def reset_admin(org_id):
    org = _get_org(org_id)
    admin = User.query.filter_by(organisation_id=org.id, role="admin").first()
    if not admin:
        abort(404)
    pw = new_temp_password()
    admin.set_password(pw)
    admin.must_change_password = True
    services.audit(org.id, "org.reset_admin_password", current_user)
    db.session.commit()
    return _show_temp(org, admin, pw, "Admin password reset")


@bp.route("/orgs/<int:org_id>/replace-admin", methods=["POST"])
@platform_required
def replace_admin(org_id):
    org = _get_org(org_id)
    try:
        admin, pw = services.replace_admin(org, request.form.get("admin_name"),
                                           request.form.get("admin_email"), current_user)
        db.session.commit()
    except services.ServiceError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("platform.edit_org", org_id=org.id))
    return _show_temp(org, admin, pw, "Admin replaced")
