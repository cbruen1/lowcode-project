import io
import json
from datetime import date, datetime, time, timedelta

import qrcode
from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user
from sqlalchemy import func, or_

from ..extensions import db
from ..models import Attendance, AuditLog, Class, Enrolment, Session, Student, User
from ..security import (admin_required, get_class_or_404, get_session_or_404, get_student_or_404,
                        login_required_user)
from .. import services
from ..timeutil import next_weekday_on_or_after, now_utc, today_local, utc_to_local

bp = Blueprint("tutor", __name__)


def _org():
    return current_user.organisation


def _visible_classes():
    q = Class.query.filter_by(organisation_id=current_user.organisation_id)
    if not current_user.is_admin:
        q = q.filter_by(tutor_id=current_user.id)
    return q


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _parse_class_form(f):
    name = (f.get("name") or "").strip()
    if not name:
        raise services.ServiceError("Enter a class name.")
    try:
        weekday = int(f.get("weekday"))
        assert 0 <= weekday <= 6
        hh, mm = (f.get("start_time") or "").split(":")[:2]
        start = time(int(hh), int(mm))
    except (TypeError, ValueError, AssertionError):
        raise services.ServiceError("Choose a weekday and start time.")
    return dict(
        name=name[:200], description=(f.get("description") or "").strip()[:2000],
        weekday=weekday, start_time=start,
        duration_minutes=_int(f.get("duration_minutes"), 60, 5, 600),
        late_after_minutes=_int(f.get("late_after_minutes"), 10, 0, 240),
        qr_checkin_enabled=f.get("qr_checkin_enabled") == "1",
        checkin_opens_before_minutes=_int(f.get("checkin_opens_before_minutes"), 15, 0, 240),
        checkin_closes_after_minutes=_int(f.get("checkin_closes_after_minutes"), 30, 0, 600),
    )


# ---------------- classes ----------------
@bp.route("/classes")
@login_required_user
def classes():
    tz = _org().time_zone
    today = today_local(tz)
    items = []
    for c in _visible_classes().order_by(Class.name).all():
        if not c.ended_on:
            services.ensure_sessions(c)
        nxt = Session.query.filter(Session.class_id == c.id, Session.date >= today,
                                   Session.status == "scheduled").order_by(Session.date).first()
        items.append((c, nxt, len(c.enrolments)))
    db.session.commit()
    active = [i for i in items if not i[0].ended_on]
    ended = [i for i in items if i[0].ended_on]
    return render_template("classes.html", active=active, ended=ended)


@bp.route("/classes/new", methods=["GET", "POST"])
@login_required_user
def class_new():
    error, f = None, request.form
    tz = _org().time_zone
    if request.method == "POST":
        try:
            data = _parse_class_form(f)
            try:
                first = date.fromisoformat(f.get("first_date", ""))
            except ValueError:
                raise services.ServiceError("Choose the date of the first class.")
            if first.weekday() != data["weekday"]:
                first = next_weekday_on_or_after(first, data["weekday"])
            c = Class(organisation_id=current_user.organisation_id, tutor_id=current_user.id,
                      first_date=first, **data)
            db.session.add(c)
            db.session.flush()
            services.ensure_sessions(c)
            services.audit(c.organisation_id, "class.create", current_user, class_id=c.id)
            db.session.commit()
            return redirect(url_for("tutor.class_detail", class_id=c.id))
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    return render_template("class_form.html", cls=None, error=error, f=f, today=today_local(tz))


@bp.route("/classes/<int:class_id>")
@login_required_user
def class_detail(class_id):
    c = get_class_or_404(class_id)
    if not c.ended_on:
        services.ensure_sessions(c)
        db.session.commit()
    tz = _org().time_zone
    today = today_local(tz)
    sessions = Session.query.filter_by(class_id=c.id).order_by(Session.date).all()
    upcoming = [s for s in sessions if s.date >= today][:8]
    past = [s for s in sessions if s.date < today][-8:][::-1]
    counts = {}
    for sid, st, n in db.session.query(Attendance.session_id, Attendance.status, func.count()) \
            .filter(Attendance.session_id.in_([s.id for s in sessions] or [0])).group_by(
            Attendance.session_id, Attendance.status):
        counts.setdefault(sid, {})[st] = n
    enrolled_ids = {e.student_id for e in c.enrolments}
    available = Student.query.filter_by(organisation_id=c.organisation_id).order_by(Student.name).all()
    available = [s for s in available if s.id not in enrolled_ids]
    tutors = User.query.filter_by(organisation_id=c.organisation_id, active=True).order_by(User.name).all() \
        if current_user.is_admin else []
    return render_template("class_detail.html", cls=c, upcoming=upcoming, past=past, counts=counts,
                           today=today, available=available, tutors=tutors,
                           roster=sorted(c.enrolments, key=lambda e: e.student.name.lower()))


@bp.route("/classes/<int:class_id>/edit", methods=["GET", "POST"])
@login_required_user
def class_edit(class_id):
    c = get_class_or_404(class_id)
    error, f = None, request.form
    if request.method == "POST":
        try:
            data = _parse_class_form(f)
            old_weekday = c.weekday
            changed = (data["weekday"], data["start_time"], data["duration_minutes"]) != \
                      (c.weekday, c.start_time, c.duration_minutes)
            for k, v in data.items():
                setattr(c, k, v)
            if changed:
                services.reschedule_future(c, old_weekday)
            services.audit(c.organisation_id, "class.update", current_user, class_id=c.id)
            db.session.commit()
            flash("Class saved.", "ok")
            return redirect(url_for("tutor.class_detail", class_id=c.id))
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    return render_template("class_form.html", cls=c, error=error, f=f, today=today_local(_org().time_zone))


@bp.route("/classes/<int:class_id>/end", methods=["POST"])
@login_required_user
def class_end(class_id):
    c = get_class_or_404(class_id)
    services.end_class(c, current_user)
    db.session.commit()
    flash("Class ended. Past sessions and attendance are kept.", "ok")
    return redirect(url_for("tutor.class_detail", class_id=c.id))


@bp.route("/classes/<int:class_id>/owner", methods=["POST"])
@admin_required
def class_owner(class_id):
    c = get_class_or_404(class_id)
    u = db.session.get(User, request.form.get("tutor_id", type=int) or 0)
    if u is None or u.organisation_id != c.organisation_id or not u.active:
        abort(404)
    c.tutor_id = u.id
    services.audit(c.organisation_id, "class.reassign", current_user, class_id=c.id)
    db.session.commit()
    flash("Class owner changed.", "ok")
    return redirect(url_for("tutor.class_detail", class_id=c.id))


@bp.route("/classes/<int:class_id>/enrol", methods=["POST"])
@login_required_user
def class_enrol(class_id):
    c = get_class_or_404(class_id)
    st = get_student_or_404(request.form.get("student_id", type=int) or 0)
    services.enrol(c, st)
    db.session.commit()
    return redirect(url_for("tutor.class_detail", class_id=c.id) + "#roster")


@bp.route("/classes/<int:class_id>/unenrol", methods=["POST"])
@login_required_user
def class_unenrol(class_id):
    c = get_class_or_404(class_id)
    st = get_student_or_404(request.form.get("student_id", type=int) or 0)
    services.unenrol(c, st)
    db.session.commit()
    return redirect(url_for("tutor.class_detail", class_id=c.id) + "#roster")


@bp.route("/classes/<int:class_id>/import", methods=["GET", "POST"])
@login_required_user
def class_import(class_id):
    c = get_class_or_404(class_id)
    return _import_view(c)


@bp.route("/students/import", methods=["GET", "POST"])
@login_required_user
def students_import():
    return _import_view(None)


def _import_view(cls):
    rows, text, error = None, "", None
    if request.method == "POST":
        if request.form.get("confirm") == "1":
            text = request.form.get("csv", "")
            rows = services.parse_csv(text)
            created, linked = services.apply_import(current_user.organisation_id, rows, cls, current_user)
            db.session.commit()
            flash(f"Imported: {created} new, {linked} already registered.", "ok")
            return redirect(url_for("tutor.class_detail", class_id=cls.id) if cls else url_for("tutor.students"))
        upload = request.files.get("file")
        raw = upload.read() if upload and upload.filename else (request.form.get("csv", "").encode())
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
            error = "Please save the file as UTF-8 CSV."
        if text and not error:
            rows = services.preview_import(current_user.organisation_id, services.parse_csv(text))
            if not rows:
                error = "No rows found. Use two columns: name, email."
                rows = None
    return render_template("import.html", cls=cls, rows=rows, text=text, error=error)


# ---------------- sessions ----------------
def _session_data(s):
    c = s.class_
    att = {a.student_id: a for a in s.attendance if a.student_id}
    enrolled = sorted((e.student for e in c.enrolments), key=lambda st: st.name.lower())
    review = [a for a in s.attendance if not a.enrolled]
    recorded = [a for a in s.attendance if a.enrolled]
    return att, enrolled, review, recorded


def _live_version(s):
    last = db.session.query(func.max(Attendance.recorded_at), func.count()).filter_by(session_id=s.id).one()
    return f"{s.status}:{last[1]}:{last[0]}"


@bp.route("/sessions/<int:session_id>")
@login_required_user
def session_view(session_id):
    s = get_session_or_404(session_id)
    att, enrolled, review, recorded = _session_data(s)
    tz = _org().time_zone
    counts = {k: sum(1 for a in s.attendance if a.status == k) for k in ("present", "late", "absent")}
    counts["pending"] = sum(1 for st in enrolled if st.id not in att)
    in_future = s.date > today_local(tz)
    tile_students = enrolled
    # Students recorded but no longer enrolled still appear
    extra_ids = {a.student_id for a in s.attendance if a.student_id} - {st.id for st in enrolled}
    if extra_ids:
        tile_students = enrolled + Student.query.filter(Student.id.in_(extra_ids)).all()
    enrolled_ids = {e.student_id for e in s.class_.enrolments}
    others = [st for st in Student.query.filter_by(organisation_id=s.class_.organisation_id)
              .order_by(Student.name) if st.id not in enrolled_ids and st.id not in extra_ids]
    return render_template("session.html", s=s, cls=s.class_, att=att, students=tile_students,
                           review=review, counts=counts, in_future=in_future, others=others,
                           live_version=_live_version(s))


@bp.route("/sessions/<int:session_id>/live.json")
@login_required_user
def session_live(session_id):
    s = get_session_or_404(session_id)
    return jsonify(v=_live_version(s))


def _back(s, anchor=""):
    return redirect(url_for("tutor.session_view", session_id=s.id) + anchor)


@bp.route("/sessions/<int:session_id>/mark", methods=["POST"])
@login_required_user
def session_mark(session_id):
    s = get_session_or_404(session_id)
    st = get_student_or_404(request.form.get("student_id", type=int) or 0)
    try:
        services.record(s, st, request.form.get("status", ""), current_user)
        db.session.commit()
    except services.ServiceError as e:
        db.session.rollback()
        flash(str(e), "error")
    return _back(s, f"#st{st.id}")


@bp.route("/sessions/<int:session_id>/mark-all", methods=["POST"])
@login_required_user
def session_mark_all(session_id):
    s = get_session_or_404(session_id)
    try:
        services.mark_all_present(s, current_user)
        db.session.commit()
    except services.ServiceError as e:
        db.session.rollback()
        flash(str(e), "error")
    return _back(s)


@bp.route("/sessions/<int:session_id>/add", methods=["POST"])
@login_required_user
def session_add(session_id):
    s = get_session_or_404(session_id)
    st = get_student_or_404(request.form.get("student_id", type=int) or 0)
    try:
        services.record(s, st, "present", current_user)
        db.session.commit()
    except services.ServiceError as e:
        db.session.rollback()
        flash(str(e), "error")
    return _back(s, f"#st{st.id}")


@bp.route("/sessions/<int:session_id>/<action>", methods=["POST"])
@login_required_user
def session_status(session_id, action):
    if action not in ("cancel", "restore"):
        abort(404)
    s = get_session_or_404(session_id)
    services.set_session_status(s, "cancelled" if action == "cancel" else "scheduled", current_user)
    db.session.commit()
    return _back(s)


@bp.route("/sessions/<int:session_id>/resolve/<int:att_id>", methods=["POST"])
@login_required_user
def session_resolve(session_id, att_id):
    s = get_session_or_404(session_id)
    a = db.session.get(Attendance, att_id)
    if a is None or a.session_id != s.id:
        abort(404)
    services.resolve_unmatched(a, current_user)
    db.session.commit()
    return _back(s)


@bp.route("/sessions/<int:session_id>/qr")
@login_required_user
def session_qr(session_id):
    s = get_session_or_404(session_id)
    if not s.class_.qr_checkin_enabled:
        flash("Turn on QR check-in for this class first.", "error")
        return redirect(url_for("tutor.class_edit", class_id=s.class_id))
    from flask import current_app
    url = current_app.config["BASE_URL"].rstrip("/") + url_for("checkin.checkin", token=s.qr_token)
    return render_template("qr.html", s=s, cls=s.class_, url=url, svg=_qr_path(url),
                           state=services.checkin_state(s), opens_local=utc_to_local(services.checkin_window(s)[0], _org().time_zone),
                           live_version=_live_version(s))


def _qr_path(data):
    """QR as one SVG path built from the module matrix (no inline styles, CSP safe)."""
    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    parts = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return n, "".join(parts)


# ---------------- grid ----------------
@bp.route("/classes/<int:class_id>/grid")
@login_required_user
def class_grid(class_id):
    c = get_class_or_404(class_id)
    today = today_local(_org().time_zone)
    sessions = Session.query.filter(Session.class_id == c.id, Session.date <= today) \
        .order_by(Session.date.desc()).limit(26).all()[::-1]
    ids = [s.id for s in sessions] or [0]
    cell = {(a.session_id, a.student_id): a.status for a in
            Attendance.query.filter(Attendance.session_id.in_(ids), Attendance.student_id.isnot(None))}
    roster = sorted((e.student for e in c.enrolments), key=lambda st: st.name.lower())
    return render_template("grid.html", cls=c, sessions=sessions, roster=roster, cell=cell)


# ---------------- students ----------------
@bp.route("/students", methods=["GET", "POST"])
@login_required_user
def students():
    org_id = current_user.organisation_id
    error = None
    if request.method == "POST":
        try:
            st, was_new = services.create_student(org_id, request.form.get("name"), request.form.get("email"))
            db.session.commit()
            flash("Student added." if was_new else "That email is already registered; showing the existing student.", "ok")
            return redirect(url_for("tutor.students", selected=st.id))
        except services.ServiceError as e:
            db.session.rollback()
            error = str(e)
    q = (request.args.get("q") or "").strip()
    query = Student.query.filter_by(organisation_id=org_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Student.name).like(like), Student.email.like(like)))
    people = query.order_by(func.lower(Student.name)).all()
    selected, detail = None, None
    sel_id = request.args.get("selected", type=int)
    if sel_id:
        selected = Student.query.filter_by(id=sel_id, organisation_id=org_id).first()
        if selected:
            classes = [e.class_ for e in Enrolment.query.filter_by(student_id=selected.id)
                       if current_user.is_admin or e.class_.tutor_id == current_user.id]
            total = Attendance.query.filter_by(student_id=selected.id)
            detail = dict(classes=classes, present=total.filter_by(status="present").count(),
                          late=total.filter_by(status="late").count(),
                          absent=total.filter_by(status="absent").count())
    return render_template("students.html", people=people, q=q, selected=selected, detail=detail, error=error)


@bp.route("/students/<int:student_id>/delete", methods=["GET", "POST"])
@login_required_user
def student_delete(student_id):
    st = get_student_or_404(student_id)
    if request.method == "POST":
        if request.form.get("confirm") != "DELETE":
            flash('Type DELETE to confirm.', "error")
        else:
            services.delete_student_data(st, current_user)
            db.session.commit()
            flash("Student and all their attendance data deleted.", "ok")
            return redirect(url_for("tutor.students"))
    n = Attendance.query.filter_by(student_id=st.id).count()
    return render_template("student_delete.html", st=st, n=n)


# ---------------- audit ----------------
@bp.route("/audit")
@login_required_user
def audit_log():
    q = AuditLog.query.filter_by(organisation_id=current_user.organisation_id)
    if not current_user.is_admin:
        ids = [c.id for c in _visible_classes()] or [0]
        q = q.filter(AuditLog.class_id.in_(ids))
    entries = q.order_by(AuditLog.id.desc()).limit(200).all()
    classes = {c.id: c for c in Class.query.filter_by(organisation_id=current_user.organisation_id)}
    tz = _org().time_zone
    rows = []
    for e in entries:
        rows.append(dict(
            when=utc_to_local(e.timestamp, tz), actor=_actor_label(e),
            action=e.action, cls=classes.get(e.class_id), session_id=e.session_id,
            before=json.loads(e.before) if e.before else None, after=json.loads(e.after) if e.after else None))
    return render_template("audit.html", rows=rows)


def _actor_label(e):
    if e.user:
        return e.user.name
    if e.platform_owner_id:
        return "Platform"
    return "Student check-in" if e.action.startswith("attendance.self") else "System"
