from datetime import datetime, time

import pytest

from app import create_app, services, timeutil
from app.config import TestConfig
from app.extensions import db
from app.models import Class, PlatformOwner, Student, User


@pytest.fixture()
def app():
    app = create_app(TestConfig)

    @app.before_request
    def _isolate_login_between_clients():
        # The fixture keeps one app context open, so g would leak the cached login across test clients.
        from flask import g
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def freeze(monkeypatch):
    def _freeze(dt: datetime):
        monkeypatch.setattr(timeutil, "now_utc", lambda: dt)
        monkeypatch.setattr(services, "now_utc", lambda: dt)
    return _freeze


def make_org(name="Org A", tz="Europe/Dublin", admin_email="admin@a.test"):
    org, admin, _ = services.create_organisation(name, tz, "", "Admin " + name, admin_email)
    admin.set_password("password-123")
    admin.must_change_password = False
    db.session.commit()
    return org, admin


def make_tutor(org, email, name="Tutor"):
    u, _ = services.create_user(org, name, email)
    u.set_password("password-123")
    u.must_change_password = False
    db.session.commit()
    return u


def make_class(org, tutor, name="Maths", weekday=0, start=time(19, 0), first=None, **kw):
    from datetime import date
    c = Class(organisation_id=org.id, tutor_id=tutor.id, name=name, weekday=weekday, start_time=start,
              first_date=first or date(2026, 1, 5), **kw)
    db.session.add(c)
    db.session.flush()
    return c


def login(client, email, password="password-123", path="/login"):
    return client.post(path, data={"email": email, "password": password}, follow_redirects=False)


@pytest.fixture()
def world(app, freeze):
    """Two orgs, each with admin and a tutor with a class and students."""
    freeze(datetime(2026, 5, 4, 12, 0))  # a Monday
    a, admin_a = make_org("Org A", admin_email="admin@a.test")
    b, admin_b = make_org("Org B", admin_email="admin@b.test")
    ta, ta2 = make_tutor(a, "t1@a.test"), make_tutor(a, "t2@a.test")
    tb = make_tutor(b, "t@b.test")
    ca = make_class(a, ta, "A class", first=datetime(2026, 4, 6).date())
    cb = make_class(b, tb, "B class", first=datetime(2026, 4, 6).date())
    cx = make_class(a, ta2, "Other tutor class", first=datetime(2026, 4, 6).date())
    s1, _ = services.create_student(a.id, "Aoife Murphy", "aoife@x.test")
    s2, _ = services.create_student(a.id, "Cian Byrne", "cian@x.test")
    sb, _ = services.create_student(b.id, "Bea Other", "bea@x.test")
    for c in (ca, cb, cx):
        services.ensure_sessions(c)
    services.enrol(ca, s1)
    services.enrol(ca, s2)
    db.session.commit()
    return dict(a=a, b=b, admin_a=admin_a, admin_b=admin_b, ta=ta, ta2=ta2, tb=tb, ca=ca, cb=cb, cx=cx,
                s1=s1, s2=s2, sb=sb)


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    from argon2 import PasswordHasher
    from app import models
    monkeypatch.setattr(models, "_ph", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
