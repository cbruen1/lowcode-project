from flask import Blueprint, abort, current_app, render_template, request

from ..extensions import db, limiter
from ..models import Session
from .. import services

bp = Blueprint("checkin", __name__)

MESSAGES = {
    "not_open": "Check-in isn't open yet. Please try again closer to the start time.",
    "closed": "Check-in for this session has closed. Please speak to your tutor.",
    "cancelled": "This session has been cancelled.",
    "disabled": "Check-in isn't available for this class.",
    "duplicate": "You've already checked in for this session.",
    "invalid_name": "Please enter your full name.",
    "invalid_email": "Please enter a valid email address.",
}


@bp.route("/checkin/<token>", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["CHECKIN_RATE"], methods=["POST"])
def checkin(token):
    s = Session.query.filter_by(qr_token=token).first()
    if s is None:
        abort(404)
    c = s.class_
    ctx = dict(cls=c, org=c.organisation, notice=current_app.config["PRIVACY_NOTICE"], f=request.form)
    state = services.checkin_state(s)
    if request.method == "POST":
        try:
            row = services.self_checkin(s, request.form.get("name"), request.form.get("email"))
            db.session.commit()
            return render_template("checkin.html", done=row, state="open", **ctx)
        except services.ServiceError as e:
            db.session.rollback()
            key = str(e)
            return render_template("checkin.html", state=state, error=MESSAGES.get(key, key), **ctx)
    return render_template("checkin.html", state=state, error=MESSAGES.get(state) if state != "open" else None, **ctx)
