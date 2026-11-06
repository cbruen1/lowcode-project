from datetime import date, datetime

import pytest

from app import services
from app.extensions import db
from app.models import Attendance, Session


@pytest.fixture()
def sess(world):
    world["ca"].qr_checkin_enabled = True
    db.session.commit()
    return Session.query.filter_by(class_id=world["ca"].id, date=date(2026, 5, 4)).one()  # starts 18:00 UTC


def at(freeze, h, m):
    freeze(datetime(2026, 5, 4, h, m))


def test_window_states(sess, freeze):
    at(freeze, 17, 30); assert services.checkin_state(sess) == "not_open"
    at(freeze, 17, 45); assert services.checkin_state(sess) == "open"
    at(freeze, 18, 30); assert services.checkin_state(sess) == "open"
    at(freeze, 18, 31); assert services.checkin_state(sess) == "closed"


def test_disabled_and_cancelled(world, sess, freeze):
    at(freeze, 18, 0)
    services.set_session_status(sess, "cancelled", world["ta"])
    assert services.checkin_state(sess) == "cancelled"
    world["ca"].qr_checkin_enabled = False
    assert services.checkin_state(sess) == "disabled"


def test_present_then_late_cutoff(world, sess, freeze):
    at(freeze, 18, 5)
    r = services.self_checkin(sess, "Aoife Murphy", "AOIFE@x.test")
    assert r.status == "present" and r.enrolled and r.student_id == world["s1"].id
    at(freeze, 18, 11)
    r2 = services.self_checkin(sess, "Cian Byrne", "cian@x.test")
    assert r2.status == "late"


def test_duplicate_blocked(sess, freeze):
    at(freeze, 18, 0)
    services.self_checkin(sess, "Aoife Murphy", "aoife@x.test")
    with pytest.raises(services.ServiceError, match="duplicate"):
        services.self_checkin(sess, "Aoife Murphy", "aoife@x.test")


def test_duplicate_blocked_after_tutor_marked(world, sess, freeze):
    at(freeze, 18, 0)
    services.record(sess, world["s1"], "absent", world["ta"])
    with pytest.raises(services.ServiceError, match="duplicate"):
        services.self_checkin(sess, "Aoife Murphy", "aoife@x.test")


def test_unknown_email_accepted_and_flagged_then_resolved(world, sess, freeze):
    at(freeze, 18, 0)
    r = services.self_checkin(sess, "Stranger Danger", "stranger@x.test")
    assert r.student_id is None and r.enrolled is False
    services.resolve_unmatched(r, world["ta"])
    db.session.commit()
    assert r.enrolled and r.student_id
    assert any(e.student_id == r.student_id for e in world["ca"].enrolments)


def test_registered_but_not_enrolled_is_flagged(world, sess, freeze):
    at(freeze, 18, 0)
    new, _ = services.create_student(world["a"].id, "Reg Student", "reg@x.test")
    r = services.self_checkin(sess, "Reg Student", "reg@x.test")
    assert r.student_id == new.id and r.enrolled is False


def test_validation(sess, freeze):
    at(freeze, 18, 0)
    with pytest.raises(services.ServiceError, match="invalid_name"):
        services.self_checkin(sess, "  ", "a@b.co")
    with pytest.raises(services.ServiceError, match="invalid_email"):
        services.self_checkin(sess, "A", "nope")


def test_tokens_are_long_and_unique(world):
    toks = [s.qr_token for s in Session.query.all()]
    assert len(toks) == len(set(toks)) and all(len(t) >= 32 for t in toks)


def test_public_page_and_post(app, world, sess, freeze):
    at(freeze, 18, 0)
    c = app.test_client()
    page = c.get(f"/checkin/{sess.qr_token}")
    assert page.status_code == 200 and b"Full name" in page.data and b"recorded" in page.data
    ok = c.post(f"/checkin/{sess.qr_token}", data={"name": "Aoife Murphy", "email": "aoife@x.test"})
    assert b"checked in" in ok.data
    dup = c.post(f"/checkin/{sess.qr_token}", data={"name": "Aoife Murphy", "email": "aoife@x.test"})
    assert b"already checked in" in dup.data
    assert c.get("/checkin/not-a-token").status_code == 404
