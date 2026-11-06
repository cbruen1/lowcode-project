import getpass
import sys

import click

from .extensions import db
from .models import Organisation, PlatformOwner
from . import services


def register(app):
    @app.cli.command("init-platform-owner")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--password", default=None)
    def init_platform_owner(name, email, password):
        """Create a platform owner (the first one is created here)."""
        password = password or getpass.getpass("Password (min 10 chars): ")
        if len(password) < 10:
            click.echo("Password too short.")
            sys.exit(1)
        p = PlatformOwner(name=name, email=email.strip().lower())
        p.set_password(password)
        db.session.add(p)
        db.session.commit()
        click.echo(f"Platform owner created: {p.email}")

    @app.cli.command("create-organisation")
    @click.option("--name", prompt=True)
    @click.option("--admin-name", prompt=True)
    @click.option("--admin-email", prompt=True)
    @click.option("--time-zone", default="Europe/Dublin")
    @click.option("--privacy-email", default="")
    def create_organisation(name, admin_name, admin_email, time_zone, privacy_email):
        org, admin, pw = services.create_organisation(name, time_zone, privacy_email, admin_name, admin_email)
        db.session.commit()
        click.echo(f"Organisation #{org.id} created.\nAdmin: {admin.email}\nTemporary password: {pw}")

    @app.cli.command("delete-organisation")
    @click.argument("org_id", type=int)
    @click.option("--yes", is_flag=True, help="Skip confirmation")
    def delete_organisation(org_id, yes):
        """Permanently delete an organisation and ALL its data."""
        org = db.session.get(Organisation, org_id)
        if not org:
            click.echo("No such organisation.")
            sys.exit(1)
        if not yes and click.prompt(f'Type the organisation name "{org.name}" to confirm') != org.name:
            click.echo("Aborted.")
            sys.exit(1)
        services.delete_organisation(org)
        db.session.commit()
        click.echo("Deleted.")

    @app.cli.command("top-up-sessions")
    def top_up_sessions():
        """Create upcoming sessions for all active classes (run daily)."""
        click.echo(f"Created {services.top_up_all(app.config['SESSIONS_AHEAD_WEEKS'])} sessions.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Create a demo organisation with a tutor and students."""
        from datetime import time
        from .models import Class
        from .timeutil import today_local
        org, admin, pw = services.create_organisation("Demo School", "Europe/Dublin", "privacy@demo.test",
                                                      "Demo Admin", "admin@demo.test")
        tutor, tpw = services.create_user(org, "Demo Tutor", "tutor@demo.test")
        for n, e in [("Aoife Murphy", "aoife@demo.test"), ("Cian O'Brien", "cian@demo.test"),
                     ("Saoirse Walsh", "saoirse@demo.test"), ("Liam Byrne", "liam@demo.test")]:
            services.create_student(org.id, n, e)
        db.session.flush()
        c = Class(organisation_id=org.id, tutor_id=tutor.id, name="Maths 101", weekday=0,
                  start_time=time(19, 0), duration_minutes=60,
                  first_date=today_local(org.time_zone))
        db.session.add(c)
        db.session.flush()
        from .models import Student
        for st in Student.query.filter_by(organisation_id=org.id):
            services.enrol(c, st)
        services.ensure_sessions(c)
        db.session.commit()
        click.echo(f"admin@demo.test / {pw}\ntutor@demo.test / {tpw}")
