from datetime import date, datetime, time

import pytest

from app import services
from app.extensions import db
from app.models import Attendance, AuditLog, Session, Student
from conftest import make_class


def test_sessions_generated_weekly_rolling_window(world):
    ca = world["ca"]
    dates = [s.date for s in Session.query.filter_by(class_id=ca.id).order_by(Session.date)]
    assert dates[0] == date(2026, 4, 6)
    assert dates[-1] == date(2026, 7, 27)  # today (4 May) + 12 weeks = 27 Jul, a Monday
    assert all(d.weekday() == 0 for d in dates)


def test_ensure_sessions_is_idempotent(world):
    assert services.ensure_sessions(world["ca"]) == 0


def test_sessions_use_local_time_across_dst(world):
    ca = world["ca"]
    s_before = Session.query.filter_by(class_id=ca.id, date=date(2026, 4, 6)).one()
    assert s_before.starts_at == datetime(2026, 4, 6, 18, 0)  # IST: 19:00 local = 18:00 UTC
    # a class created in winter crossing into summer
    c = make_class(world["a"], world["ta"], "Winter", first=date(2026, 3, 16))
    services.ensure_sessions(c)
    got = {s.date: s.starts_at.hour for s in Session.query.filter_by(class_id=c.id)}
    assert got[date(2026, 3, 23)] == 19 and got[date(2026, 3, 30)] == 18


def test_top_up_rolls_forward(world, freeze):
    freeze(datetime(2026, 6, 1, 12, 0))
    assert services.top_up_all() > 0
    last = Session.query.filter_by(class_id=world["ca"].id).order_by(Session.date.desc()).first()
    assert last.date == date(2026, 8, 24)


def test_end_class_removes_future_keeps_past(world):
    services.end_class(world["ca"], world["ta"])
    db.session.commit()
    dates = [s.date for s in Session.query.filter_by(class_id=world["ca"].id)]
    assert max(dates) == date(2026, 5, 4)
    services.ensure_sessions(world["ca"])
    assert max(s.date for s in Session.query.filter_by(class_id=world["ca"].id)) == date(2026, 5, 4)


def test_reschedule_only_touches_future_without_attendance(world):
    ca = world["ca"]
    past = Session.query.filter_by(class_id=ca.id, date=date(2026, 4, 13)).one()
    kept = Session.query.filter_by(class_id=ca.id, date=date(2026, 5, 11)).one()
    services.record(past, world["s1"], "present", world["ta"])
    db.session.commit()
    old_start = past.starts_at
    ca.start_time = time(20, 0)
    services.reschedule_future(ca, ca.weekday)
    db.session.commit()
    assert past.starts_at == old_start
    assert kept.starts_at == datetime(2026, 5, 11, 19, 0)  # 20:00 IST


def test_reschedule_weekday_regenerates_future(world):
    ca = world["ca"]
    ca.weekday = 2
    services.reschedule_future(ca, 0)
    db.session.commit()
    future = [s for s in Session.query.filter_by(class_id=ca.id) if s.date > date(2026, 5, 4)]
    assert future and all(s.date.weekday() == 2 for s in future)
    past = [s for s in Session.query.filter_by(class_id=ca.id) if s.date < date(2026, 5, 4)]
    assert all(s.date.weekday() == 0 for s in past)


def _session(world, d):
    return Session.query.filter_by(class_id=world["ca"].id, date=d).one()


def test_record_and_audit(world):
    s = _session(world, date(2026, 5, 4))
    services.record(s, world["s1"], "present", world["ta"])
    services.record(s, world["s1"], "late", world["ta"])
    db.session.commit()
    acts = [a.action for a in AuditLog.query.filter_by(session_id=s.id).order_by(AuditLog.id)]
    assert acts == ["attendance.create", "attendance.update"]
    row = Attendance.query.filter_by(session_id=s.id, student_id=world["s1"].id).one()
    assert row.status == "late"


def test_not_recorded_differs_from_absent(world):
    s = _session(world, date(2026, 5, 4))
    services.record(s, world["s1"], "absent", world["ta"])
    services.record(s, world["s2"], "present", world["ta"])
    services.record(s, world["s2"], "none", world["ta"])
    db.session.commit()
    assert Attendance.query.filter_by(session_id=s.id, student_id=world["s1"].id).one().status == "absent"
    assert Attendance.query.filter_by(session_id=s.id, student_id=world["s2"].id).first() is None


def test_future_and_cancelled_sessions_cannot_be_recorded(world):
    fut = _session(world, date(2026, 5, 11))
    with pytest.raises(services.ServiceError):
        services.record(fut, world["s1"], "present", world["ta"])
    today = _session(world, date(2026, 5, 4))
    services.set_session_status(today, "cancelled", world["ta"])
    with pytest.raises(services.ServiceError):
        services.record(today, world["s1"], "present", world["ta"])


def test_mark_all_present_skips_already_recorded(world):
    s = _session(world, date(2026, 5, 4))
    services.record(s, world["s1"], "absent", world["ta"])
    assert services.mark_all_present(s, world["ta"]) == 1
    db.session.commit()
    assert Attendance.query.filter_by(session_id=s.id, student_id=world["s1"].id).one().status == "absent"


def test_adding_non_enrolled_student_enrols_them(world):
    from app.models import Enrolment
    ca = world["ca"]
    new, _ = services.create_student(world["a"].id, "New Kid", "new@x.test")
    s = _session(world, date(2026, 5, 4))
    services.record(s, new, "present", world["ta"])
    db.session.commit()
    assert Enrolment.query.filter_by(class_id=ca.id, student_id=new.id).count() == 1


def test_cannot_record_student_from_other_org(world):
    s = _session(world, date(2026, 5, 4))
    with pytest.raises(services.ServiceError):
        services.record(s, world["sb"], "present", world["ta"])


def test_csv_parse_and_import(world):
    rows = services.parse_csv("name,email\nAoife Murphy,aoife@x.test\nNew One,new@x.test\nBad,notanemail\n,x@y.test\nNew One,NEW@x.test\n")
    rows = services.preview_import(world["a"].id, rows)
    assert [r["status"] for r in rows] == ["existing", "new", "invalid", "invalid", "duplicate"]
    created, linked = services.apply_import(world["a"].id, rows, world["ca"], world["ta"])
    db.session.commit()
    assert (created, linked) == (1, 1)
    assert Student.query.filter_by(organisation_id=world["a"].id, email="new@x.test").count() == 1


def test_gdpr_delete_removes_everything_personal(world):
    s = _session(world, date(2026, 5, 4))
    services.record(s, world["s1"], "present", world["ta"])
    db.session.commit()
    sid = world["s1"].id
    services.delete_student_data(world["s1"], world["ta"])
    db.session.commit()
    assert db.session.get(Student, sid) is None
    assert Attendance.query.filter_by(student_id=sid).count() == 0
    for log in AuditLog.query.all():
        assert "aoife" not in ((log.before or "") + (log.after or "") + log.action).lower()


def test_gdpr_delete_removes_unmatched_self_checkins_by_email(world, freeze):
    freeze(datetime(2026, 5, 4, 18, 0))
    freeze_s = _session(world, date(2026, 5, 4))
    world["ca"].qr_checkin_enabled = True
    db.session.commit()
    services.self_checkin(freeze_s, "Aoife M", "aoife@x.test")
    db.session.commit()
    services.delete_student_data(world["s1"], world["ta"])
    db.session.commit()
    assert Attendance.query.filter_by(submitted_email="aoife@x.test").count() == 0
