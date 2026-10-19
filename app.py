from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Hello</title>
</head>
<body>
    <h1>Hello from Ciaran</h1>
</body>
</html>"""


@app.route("/about")
def about():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>About</title>
</head>
<body>
    <h1>What would I build if it took an evening instead of a quarter?</h1>
    <p>
        A tiny tool that reads a street address out loud for landlords: paste in a tenant's
        move-in date and unit number, and it emails them a countdown of what's due and when
        &mdash; rent, renewal notice, inspection windows &mdash; pulled from whatever dates
        are already in the lease PDF. No dashboard, no accounts, no onboarding flow. Just a
        form, a cron job, and a mailer. The point isn't to build a product; it's to remove
        one specific recurring annoyance (missed renewal deadlines) for one specific person
        I know who complains about it monthly. An evening is enough to prove whether the idea
        earns its keep before investing in anything more polished. If it's still being used
        in a month, that's the real signal to build further &mdash; not a roadmap drawn up
        in advance.
    </p>
</body>
</html>"""


if __name__ == "__main__":
    app.run(debug=True)
