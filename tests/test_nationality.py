"""Students carry an optional free-text nationality: manual add, CSV import, display, migration."""
import os
import sqlite3

import pytest

from app import create_app, services
from app.extensions import db
from app.models import Student
from test_infra import _cfg
from test_web import client_for


# ---------- service ----------
def test_create_student_stores_trimmed_nationality(world):
    st, _ = services.create_student(world["a"].id, "Zed One", "zed@x.test", "  Irish ")
    db.session.commit()
    assert db.session.get(Student, st.id).nationality == "Irish"


def test_create_student_nationality_is_optional(world):
    st, _ = services.create_student(world["a"].id, "Zed One", "zed@x.test")
    assert st.nationality == ""


def test_create_student_rejects_overlong_nationality(world):
    with pytest.raises(services.ServiceError):
        services.create_student(world["a"].id, "Zed One", "zed@x.test", "x" * 101)


# ---------- CSV ----------
def test_csv_third_column_is_nationality(world):
    rows = services.parse_csv("Zed One,zed@x.test, Polish \nNo Nat,nonat@x.test\n")
    assert [(r["name"], r["nationality"], r["status"]) for r in rows] == [
        ("Zed One", "Polish", "new"), ("No Nat", "", "new")]


@pytest.mark.parametrize("header", ["name,email,nationality",
                                    "student_name,student_email,student_nationality",
                                    "Student_Name,Student_Email"])
def test_csv_header_row_is_skipped(world, header):
    rows = services.parse_csv(header + "\nZed One,zed@x.test,Polish\n")
    assert [r["email"] for r in rows] == ["zed@x.test"]


def test_csv_overlong_nationality_is_invalid(world):
    rows = services.parse_csv("Zed One,zed@x.test," + "x" * 101 + "\n")
    assert rows[0]["status"] == "invalid" and "ationality" in rows[0]["error"]


def test_import_saves_nationality_for_new_students_only(world):
    rows = services.parse_csv("Zed One,zed@x.test,Polish\nAoife Murphy,aoife@x.test,French\n")
    services.apply_import(world["a"].id, rows, None, world["ta"])
    db.session.commit()
    org = world["a"].id
    assert Student.query.filter_by(organisation_id=org, email="zed@x.test").one().nationality == "Polish"
    # Existing students are linked, not overwritten.
    assert Student.query.filter_by(organisation_id=org, email="aoife@x.test").one().nationality == ""


# ---------- web ----------
def test_add_student_form_saves_and_shows_nationality(app, world):
    c = client_for(app, "t1@a.test")
    r = c.post("/students", data={"name": "Zed One", "email": "zed@x.test", "nationality": "Brazilian"},
               follow_redirects=True)
    assert r.status_code == 200
    assert b'name="nationality"' in r.data
    assert b"Brazilian" in r.data  # shown in the selected student's panel


def test_import_preview_shows_nationality(app, world):
    c = client_for(app, "t1@a.test")
    r = c.post(f"/classes/{world['ca'].id}/import", data={"csv": "Zed One,zed@x.test,Canadian\n"})
    assert b"Nationality" in r.data and b"Canadian" in r.data


# ---------- migration ----------
def test_migrations_add_nationality_column(tmp_path):
    from flask_migrate import upgrade
    path = tmp_path / "m.db"
    app = create_app(_cfg(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(path)))
    with app.app_context():
        upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    cols = {r[1]: r for r in sqlite3.connect(path).execute("pragma table_info(student)")}
    assert "nationality" in cols and cols["nationality"][3] == 1  # NOT NULL
