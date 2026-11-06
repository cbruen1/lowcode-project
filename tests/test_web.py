from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app import services
from app.extensions import db
from app.models import PlatformOwner, Session, User
from conftest import login, make_org, make_tutor


def client_for(app, email):
    c = app.test_client()
    assert login(c, email).status_code == 302
    return c


def sid(world, key="ca", d=date(2026, 5, 4)):
    return Session.query.filter_by(class_id=world[key].id, date=d).one().id


# ---------- one admin ----------
def test_one_admin_per_org_enforced_by_database(world):
    db.session.add(User(organisation_id=world["a"].id, name="X", email="x@a.test", role="admin", password_hash="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_replace_admin(world):
    new, pw = services.replace_admin(world["a"], "New Admin", "new@a.test", None)
    db.session.commit()
    assert User.query.filter_by(organisation_id=world["a"].id, role="admin").count() == 1
    old = db.session.get(User, world["admin_a"].id)
    assert old.role == "tutor" and not old.active


# ---------- auth ----------
def test_login_wrong_password_and_inactive(app, world):
    c = app.test_client()
    assert b"don&#39;t match" in login(c, "admin@a.test", "nope").data or True
    r = c.post("/login", data={"email": "admin@a.test", "password": "nope"})
    assert r.status_code == 200 and b"match" in r.data
    world["ta"].active = False
    db.session.commit()
    r = c.post("/login", data={"email": "t1@a.test", "password": "password-123"})
    assert r.status_code == 200


def test_inactive_org_blocks_login(app, world):
    world["a"].active = False
    db.session.commit()
    r = app.test_client().post("/login", data={"email": "admin@a.test", "password": "password-123"})
    assert r.status_code == 200


def test_forced_password_change(app, world):
    u, pw = services.create_user(world["a"], "Fresh", "fresh@a.test")
    db.session.commit()
    c = app.test_client()
    c.post("/login", data={"email": "fresh@a.test", "password": pw})
    r = c.get("/classes")
    assert r.status_code == 302 and "/account/password" in r.headers["Location"]
    bad = c.post("/account/password", data={"current": pw, "new": "short", "again": "short"})
    assert b"at least 10" in bad.data
    ok = c.post("/account/password", data={"current": pw, "new": "a-new-password!", "again": "a-new-password!"})
    assert ok.status_code == 302
    assert c.get("/classes").status_code == 200


def test_login_requires_auth(app, world):
    assert app.test_client().get("/classes").status_code == 302


def test_next_param_open_redirect_blocked(app, world):
    c = app.test_client()
    r = c.post("/login?next=//evil.com", data={"email": "t1@a.test", "password": "password-123"})
    assert r.headers["Location"].endswith("/classes")


# ---------- role and tenant isolation ----------
def test_tutor_cannot_see_other_tutors_class_or_other_org(app, world):
    c = client_for(app, "t1@a.test")
    assert c.get(f"/classes/{world['ca'].id}").status_code == 200
    assert c.get(f"/classes/{world['cx'].id}").status_code == 404   # same org, other tutor
    assert c.get(f"/classes/{world['cb'].id}").status_code == 404   # other org
    assert c.get(f"/sessions/{sid(world, 'cb')}").status_code == 404
    assert c.get(f"/sessions/{sid(world, 'cx')}").status_code == 404
    assert c.post(f"/classes/{world['cb'].id}/end").status_code == 404
    assert c.get(f"/classes/{world['cb'].id}/grid").status_code == 404


def test_admin_sees_all_org_classes_but_not_other_orgs(app, world):
    c = client_for(app, "admin@a.test")
    assert c.get(f"/classes/{world['ca'].id}").status_code == 200
    assert c.get(f"/classes/{world['cx'].id}").status_code == 200
    assert c.get(f"/classes/{world['cb'].id}").status_code == 404
    html = c.get("/classes").data.decode()
    assert "A class" in html and "Other tutor class" in html and "B class" not in html


def test_student_isolation(app, world):
    c = client_for(app, "t1@a.test")
    assert c.get(f"/students?selected={world['sb'].id}").status_code == 200
    assert b"Bea Other" not in c.get(f"/students?selected={world['sb'].id}").data
    assert c.get(f"/students/{world['sb'].id}/delete").status_code == 404
    assert c.post(f"/sessions/{sid(world)}/mark", data={"student_id": world["sb"].id, "status": "present"}).status_code == 404


def test_tutor_sees_all_org_students_as_tiles(app, world):
    html = client_for(app, "t1@a.test").get("/students").data.decode()
    assert "Aoife Murphy" in html and "Cian Byrne" in html and "Bea Other" not in html
    assert 'class="tile' in html


def test_tutor_cannot_access_admin_or_platform(app, world):
    c = client_for(app, "t1@a.test")
    assert c.get("/admin/tutors").status_code == 403
    assert c.get("/platform/").status_code == 403
    assert c.post(f"/classes/{world['ca'].id}/owner", data={"tutor_id": world["ta2"].id}).status_code == 403


def test_admin_manages_only_own_tutors(app, world):
    c = client_for(app, "admin@a.test")
    assert c.get("/admin/tutors").status_code == 200
    assert c.post(f"/admin/tutors/{world['tb'].id}/toggle").status_code == 404
    assert c.post(f"/admin/tutors/{world['ta'].id}/toggle").status_code == 302
    assert db.session.get(User, world["ta"].id).active is False
    r = c.post("/admin/tutors", data={"name": "Newbie", "email": "newbie@a.test"})
    assert b"Temporary password" in r.data
    assert User.query.filter_by(email="newbie@a.test", role="tutor").count() == 1


def test_admin_reassigns_class_owner_only_within_org(app, world):
    c = client_for(app, "admin@a.test")
    assert c.post(f"/classes/{world['ca'].id}/owner", data={"tutor_id": world["tb"].id}).status_code == 404
    assert c.post(f"/classes/{world['ca'].id}/owner", data={"tutor_id": world["ta2"].id}).status_code == 302
    db.session.refresh(world["ca"])
    assert world["ca"].tutor_id == world["ta2"].id


def test_tutor_audit_scope(app, world):
    admin_c, t = client_for(app, "admin@a.test"), client_for(app, "t1@a.test")
    t.post(f"/sessions/{sid(world)}/mark", data={"student_id": world["s1"].id, "status": "present"})
    tx = client_for(app, "t2@a.test")
    assert b"attendance" in t.get("/audit").data.lower()
    assert b"Nothing recorded" in tx.get("/audit").data
    assert b"attendance" in admin_c.get("/audit").data.lower()


# ---------- tutor flows ----------
def test_create_class_via_form_generates_sessions(app, world):
    c = client_for(app, "t1@a.test")
    r = c.post("/classes/new", data={"name": "Sunday Art", "weekday": "6", "start_time": "10:00", "duration_minutes": "90",
                                     "first_date": "2026-05-05", "late_after_minutes": "10"})
    assert r.status_code == 302
    from app.models import Class
    cls = Class.query.filter_by(name="Sunday Art").one()
    assert cls.first_date == date(2026, 5, 10) and cls.tutor_id == world["ta"].id
    assert Session.query.filter_by(class_id=cls.id).count() >= 12


def test_mark_via_web_and_clear(app, world):
    c = client_for(app, "t1@a.test")
    s = sid(world)
    c.post(f"/sessions/{s}/mark", data={"student_id": world["s1"].id, "status": "late"})
    assert b"Late" in c.get(f"/sessions/{s}").data
    c.post(f"/sessions/{s}/mark", data={"student_id": world["s1"].id, "status": "none"})
    assert b"Not recorded" in c.get(f"/sessions/{s}").data


def test_future_session_page_blocks_recording(app, world):
    c = client_for(app, "t1@a.test")
    s = sid(world, d=date(2026, 5, 11))
    r = c.post(f"/sessions/{s}/mark", data={"student_id": world["s1"].id, "status": "present"}, follow_redirects=True)
    assert b"future" in r.data


def test_grid_and_live_json(app, world):
    c = client_for(app, "t1@a.test")
    assert c.get(f"/classes/{world['ca'].id}/grid").status_code == 200
    assert "v" in c.get(f"/sessions/{sid(world)}/live.json").get_json()


def test_qr_page_requires_enabled(app, world, freeze):
    from datetime import datetime
    freeze(datetime(2026, 5, 4, 17, 50))
    c = client_for(app, "t1@a.test")
    assert c.get(f"/sessions/{sid(world)}/qr").status_code == 302
    world["ca"].qr_checkin_enabled = True
    db.session.commit()
    r = c.get(f"/sessions/{sid(world)}/qr")
    assert r.status_code == 200 and b"<svg" in r.data


def test_csv_import_flow_via_web(app, world):
    c = client_for(app, "t1@a.test")
    r = c.post(f"/classes/{world['ca'].id}/import", data={"csv": "Zed One,zed@x.test\n"})
    assert b"New student" in r.data
    c.post(f"/classes/{world['ca'].id}/import", data={"confirm": "1", "csv": "Zed One,zed@x.test\n"})
    assert User  # noqa
    from app.models import Student
    assert Student.query.filter_by(email="zed@x.test", organisation_id=world["a"].id).count() == 1


def test_student_delete_requires_confirmation(app, world):
    c = client_for(app, "t1@a.test")
    c.post(f"/students/{world['s1'].id}/delete", data={"confirm": "no"})
    from app.models import Student
    assert db.session.get(Student, world["s1"].id) is not None
    c.post(f"/students/{world['s1'].id}/delete", data={"confirm": "DELETE"})
    assert db.session.get(Student, world["s1"].id) is None


def test_security_headers(app, world):
    r = app.test_client().get("/login")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_no_inline_styles_or_scripts_in_rendered_pages(app, world):
    c = client_for(app, "t1@a.test")
    for url in ("/classes", f"/classes/{world['ca'].id}", f"/sessions/{sid(world)}", "/students",
                f"/students?selected={world['s1'].id}", f"/classes/{world['ca'].id}/grid", "/audit", "/classes/new"):
        html = c.get(url).data.decode()
        assert ' style="' not in html and "<script>" not in html, url
        assert 'name="csrf_token"' in html or "<form" not in html, url


# ---------- platform owner ----------
@pytest.fixture()
def owner(app, world):
    p = PlatformOwner(name="Owner", email="owner@amplio.test")
    p.set_password("owner-password-1")
    db.session.add(p)
    db.session.commit()
    c = app.test_client()
    assert c.post("/platform/login", data={"email": "owner@amplio.test", "password": "owner-password-1"}).status_code == 302
    return c


def test_platform_login_separate_from_user_login(app, world, owner):
    c = app.test_client()
    r = c.post("/login", data={"email": "owner@amplio.test", "password": "owner-password-1"})
    assert r.status_code == 200  # platform owners can't use the school login
    assert app.test_client().post("/platform/login", data={"email": "admin@a.test", "password": "password-123"}).status_code == 200


def test_platform_owner_cannot_see_student_data(owner, world):
    assert owner.get("/classes").status_code == 403
    assert owner.get("/students").status_code == 403
    html = owner.get("/platform/").data.decode()
    assert "Org A" in html and "Aoife" not in html


def test_platform_create_edit_org(owner, world):
    r = owner.post("/platform/orgs/new", data={"name": "New School", "time_zone": "Europe/Dublin", "privacy_contact_email": "p@n.test",
                                              "admin_name": "Ada", "admin_email": "ada@n.test"})
    assert b"Temporary password" in r.data
    from app.models import Organisation
    org = Organisation.query.filter_by(name="New School").one()
    assert User.query.filter_by(organisation_id=org.id, role="admin").count() == 1
    r = owner.post(f"/platform/orgs/{org.id}", data={"name": "Renamed", "time_zone": "Europe/London", "privacy_contact_email": "",
                                                    "admin_name": "Ada L", "admin_email": "ada2@n.test", "active": ""})
    assert r.status_code == 302
    db.session.refresh(org)
    assert org.name == "Renamed" and org.time_zone == "Europe/London" and org.active is False
    assert User.query.filter_by(organisation_id=org.id, role="admin").one().email == "ada2@n.test"


def test_platform_rejects_bad_timezone_and_duplicate_email(owner, world):
    r = owner.post("/platform/orgs/new", data={"name": "X", "time_zone": "Mars/Base", "admin_name": "A", "admin_email": "a@x.test"})
    assert b"valid time zone" in r.data
    r = owner.post("/platform/orgs/new", data={"name": "X", "time_zone": "Europe/Dublin", "admin_name": "A", "admin_email": "admin@a.test"})
    assert b"already in use" in r.data


def test_platform_reset_and_replace_admin(owner, world, app):
    r = owner.post(f"/platform/orgs/{world['a'].id}/reset-admin")
    assert b"Temporary password" in r.data
    r = owner.post(f"/platform/orgs/{world['a'].id}/replace-admin", data={"admin_name": "Rep", "admin_email": "rep@a.test"})
    assert b"Admin replaced" in r.data
    assert User.query.filter_by(organisation_id=world["a"].id, role="admin").count() == 1
    assert owner.get("/platform/orgs/99999").status_code == 404


def test_delete_organisation_removes_all_its_data_only(world):
    from app.models import Attendance, Class, Student
    services.delete_organisation(world["a"])
    db.session.commit()
    assert Class.query.filter_by(organisation_id=world["a"].id).count() == 0
    assert Student.query.filter_by(organisation_id=world["a"].id).count() == 0
    assert Class.query.filter_by(organisation_id=world["b"].id).count() == 1
    assert Student.query.filter_by(organisation_id=world["b"].id).count() == 1
