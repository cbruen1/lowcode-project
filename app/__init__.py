import os
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or Config)
    if config is None:
        if app.config["SECRET_KEY"] == "dev-only-change-me" and os.environ.get("FLASK_ENV") == "production":
            raise RuntimeError("Set SECRET_KEY")
        Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from . import models  # noqa: F401
    from .blueprints import admin, auth, checkin, platform, tutor
    for bp in (auth.bp, platform.bp, admin.bp, tutor.bp, checkin.bp):
        app.register_blueprint(bp)

    from .cli import register as register_cli
    register_cli(app)
    register_helpers(app)
    return app


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def register_helpers(app):
    @app.template_filter("dt")
    def fmt_date(d, fmt="%a %d %b %Y"):
        return d.strftime(fmt) if d else ""

    @app.template_filter("initials")
    def initials(name):
        parts = [p for p in (name or "").split() if p]
        return ("".join(p[0] for p in parts[:2])).upper() or "?"

    app.jinja_env.globals["WEEKDAYS"] = WEEKDAYS

    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and getattr(current_user, "must_change_password", False)
                and request.endpoint not in ("auth.change_password", "auth.logout", "static")):
            return redirect(url_for("auth.change_password"))

    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    for code, title, msg in ((403, "Not allowed", "You don't have access to this page."),
                             (404, "Not found", "We couldn't find that page."),
                             (429, "Too many requests", "Please wait a moment and try again.")):
        app.register_error_handler(code, lambda e, c=code, t=title, m=msg:
                                   (render_template("error.html", code=c, title=t, message=m), c))
