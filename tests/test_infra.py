import os
import sqlite3

import pytest

from app import create_app
from app.config import Config, TestConfig
from app.extensions import db
from conftest import make_org


def _cfg(**over):
    return type("Cfg", (TestConfig,), over)


def test_csrf_enforced_when_enabled():
    app = create_app(_cfg(WTF_CSRF_ENABLED=True))
    with app.app_context():
        db.create_all()
        r = app.test_client().post("/login", data={"email": "a@b.co", "password": "x"})
        assert r.status_code == 400
        page = app.test_client().get("/login")
        assert b'name="csrf_token"' in page.data


def test_login_rate_limited():
    app = create_app(_cfg(RATELIMIT_ENABLED=True, LOGIN_RATE="3 per minute"))
    with app.app_context():
        db.create_all()
        c = app.test_client()
        codes = [c.post("/login", data={"email": "a@b.co", "password": "x"}).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


def test_session_cookie_flags(tmp_path):
    class Prod(Config):
        DATABASE_PATH = str(tmp_path / "x.db")
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH
        SECRET_KEY = "k"
        SESSION_COOKIE_SECURE = True
        WTF_CSRF_ENABLED = False
        RATELIMIT_ENABLED = False
    app = create_app(Prod)
    with app.app_context():
        db.create_all()
        org, admin = make_org()
        r = app.test_client().post("/login", data={"email": "admin@a.test", "password": "password-123"},
                                   base_url="https://localhost")
        cookie = r.headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie
        assert "Strict-Transport-Security" in r.headers


def test_migrations_build_schema_with_partial_indexes(tmp_path):
    path = tmp_path / "m.db"
    from flask_migrate import upgrade
    app = create_app(_cfg(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path)))
    with app.app_context():
        upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    con = sqlite3.connect(path)
    names = {r[0] for r in con.execute("select name from sqlite_master where type='index'")}
    assert {"uq_one_admin_per_org", "uq_attendance_email", "uq_student_org_email"} <= names
    con.execute("pragma foreign_keys=off")
    con.execute("insert into organisation(id,name,time_zone,privacy_contact_email,active,created_at) values (1,'o','Europe/Dublin','',1,'2026-01-01')")
    ins = "insert into user(organisation_id,name,email,password_hash,role,active,must_change_password,created_at) values (1,'n',?, 'h','admin',1,0,'2026-01-01')"
    con.execute(ins, ("a@x.test",))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(ins, ("b@x.test",))
    assert con.execute("pragma journal_mode").fetchone()[0].lower() == "wal"


def test_cli_create_organisation_and_top_up(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["create-organisation", "--name", "CLI School", "--admin-name", "Ad", "--admin-email", "ad@cli.test"])
    assert "Temporary password:" in r.output
    r = runner.invoke(args=["top-up-sessions"])
    assert "Created" in r.output
    r = runner.invoke(args=["init-platform-owner", "--name", "Own", "--email", "own@x.test", "--password", "long-enough-pass"])
    assert "created" in r.output
