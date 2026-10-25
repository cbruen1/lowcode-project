import os
import re
import secrets

from flask import (Flask, flash, abort, redirect, render_template,
                   request, session, url_for)

app = Flask(__name__)
# Set a real secret in production: export SECRET_KEY=...
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

# Dot-atom local part (RFC 5322 atext) + hostname labels + alphabetic TLD.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)
# Anything that looks like the start of an HTML tag, comment, doctype or
# processing instruction: <script>, </p>, <b ...>, <!-- , <?xml
HTML_TAG_RE = re.compile(r"<(?:[A-Za-z]|/[A-Za-z]|!|\?)")
# Control characters. Names allow none; messages still allow \t \n \r.
CTRL_ALL_RE = re.compile(r"[\x00-\x1f\x7f]")
CTRL_MSG_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TOPICS = ["General enquiry", "Support", "Feedback", "Other"]


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


def validate_contact(form) -> tuple[dict, dict]:
    """Return (cleaned_values, errors)."""
    values = {
        "name": form.get("name", "").strip(),
        "email": form.get("email", "").strip(),
        "topic": form.get("topic", ""),
        "message": form.get("message", "").strip(),
    }
    errors = {}
    if not values["name"]:
        errors["name"] = "Please enter your name."
    elif len(values["name"]) > 100:
        errors["name"] = "Name must be 100 characters or fewer."
    elif "<" in values["name"] or ">" in values["name"] or CTRL_ALL_RE.search(values["name"]):
        errors["name"] = "Name contains characters that aren't allowed."
    if not EMAIL_RE.match(values["email"]) or len(values["email"]) > 254:
        errors["email"] = "Please enter a valid email address."
    if values["topic"] not in TOPICS:
        errors["topic"] = "Please choose a topic."
    if len(values["message"]) < 10:
        errors["message"] = "Message must be at least 10 characters."
    elif len(values["message"]) > 1000:
        errors["message"] = "Message must be 1000 characters or fewer."
    elif HTML_TAG_RE.search(values["message"]):
        errors["message"] = "Please remove any HTML tags (such as <b> or <script>) from your message."
    elif CTRL_MSG_RE.search(values["message"]):
        errors["message"] = "Message contains characters that aren't allowed."
    return values, errors


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        if not secrets.compare_digest(request.form.get("csrf_token", ""),
                                      session.get("csrf_token", "")):
            abort(400, "Invalid CSRF token")

        # Honeypot: pretend success so bots learn nothing.
        if request.form.get("website"):
            return redirect(url_for("contact"))

        values, errors = validate_contact(request.form)
        if errors:
            return render_template("contact.html", values=values,
                                   errors=errors, topics=TOPICS), 400

        # TODO: send an email / save to a database here.
        app.logger.info("Contact form: %s", values)

        flash("Thanks! Your message has been sent.", "success")
        return redirect(url_for("contact"))  # Post/Redirect/Get

    return render_template("contact.html", values={}, errors={}, topics=TOPICS)


if __name__ == "__main__":
    app.run(debug=True)
