from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Class, User, new_temp_password
from ..security import admin_required
from .. import services

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _tutor_or_404(uid):
    u = db.session.get(User, uid)
    if u is None or u.organisation_id != current_user.organisation_id or u.role != "tutor":
        abort(404)
    return u


@bp.route("/tutors", methods=["GET", "POST"])
@admin_required
def tutors():
    error = None
    if request.method == "POST":
        try:
            u, pw = services.create_user(current_user.organisation, request.form.get("name"),
                                         request.form.get("email"), "tutor")
            services.audit(u.organisation_id, "tutor.create", current_user)
            db.session.commit()
            return render_template("temp_password.html", org=current_user.organisation, account=u,
                                   password=pw, title="Tutor added", back=url_for("admin.tutors"))
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    rows = User.query.filter_by(organisation_id=current_user.organisation_id, role="tutor") \
        .order_by(User.active.desc(), User.name).all()
    counts = {u.id: Class.query.filter_by(tutor_id=u.id, ended_on=None).count() for u in rows}
    return render_template("tutors.html", tutors=rows, counts=counts, error=error)


@bp.route("/tutors/<int:uid>/toggle", methods=["POST"])
@admin_required
def toggle(uid):
    u = _tutor_or_404(uid)
    u.active = not u.active
    services.audit(u.organisation_id, "tutor.activate" if u.active else "tutor.deactivate", current_user)
    db.session.commit()
    return redirect(url_for("admin.tutors"))


@bp.route("/tutors/<int:uid>/reset", methods=["POST"])
@admin_required
def reset(uid):
    u = _tutor_or_404(uid)
    pw = new_temp_password()
    u.set_password(pw)
    u.must_change_password = True
    services.audit(u.organisation_id, "tutor.reset_password", current_user)
    db.session.commit()
    return render_template("temp_password.html", org=current_user.organisation, account=u, password=pw,
                           title="Password reset", back=url_for("admin.tutors"))
