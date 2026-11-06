# Attendance tracker

Multi-tenant attendance tracker for schools and organisations. Flask + SQLite. Platform owner → one admin per
organisation → tutors → weekly recurring classes, with optional QR self check-in.

## Roles
| Role | Login | Can do |
|---|---|---|
| Platform owner | `/platform/login` | Create/edit organisations (name, time zone, privacy contact, active), create the single admin, reset or replace the admin. Sees counts only, never student data. |
| Admin (one per organisation) | `/login` | Everything a tutor can do across all org classes, plus add/deactivate/reset tutors, reassign class owners, org-wide audit log. |
| Tutor | `/login` | Create own classes, create/import students, see all students in the org, record attendance in own classes. |
| Student | none | Optional QR self check-in only. |

## Run locally
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export FLASK_APP=wsgi.py SESSION_COOKIE_SECURE=0 SECRET_KEY=dev DATABASE_PATH=/tmp/dev.db
flask db upgrade
flask init-platform-owner            # first platform owner (prompts)
flask seed-demo                      # optional demo data
flask run
pytest                               # 83 tests incl. DST 2026–2028
```
Then sign in at `/platform/login`, create an organisation, and give the admin the temporary password shown once.

## Deploy (Render / Fly / Railway / any Docker PaaS)
Use the `Dockerfile` (or `Procfile`). Required environment:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Long random string. Required. |
| `DATABASE_PATH` | Path **on a persistent volume**, e.g. `/data/attendance.db`. Without a volume the data is lost on every deploy. |
| `BASE_URL` | Public URL, e.g. `https://attendance.example.com`. Used in the QR code. |
| `SESSION_COOKIE_SECURE` | Leave at `1` in production (HTTPS). `0` only for local HTTP. |
| `PRIVACY_NOTICE` | Optional. Replace the placeholder notice shown on the check-in form with your own legal text. |
| `LOGIN_RATE`, `CHECKIN_RATE` | Optional, e.g. `10 per minute`, `60 per minute`. |

First run on the server: open a shell and run `flask init-platform-owner`.

**Daily job:** run `flask top-up-sessions` once a day (cron / scheduled job) to keep ~12 weeks of sessions ahead.
The app also tops up a class when its page is opened, so a missed run is harmless.

### Docker Compose (local or a single server)
```bash
cp .env.example .env        # set SECRET_KEY (and BASE_URL if not localhost)
docker compose up --build   # http://localhost:8000
docker compose exec web flask init-platform-owner
```
Compose sets `SESSION_COOKIE_SECURE=0` by default for plain-http localhost; set it to `1` behind HTTPS.
The database lives in the `attendance-data` volume.

### Single instance only (on purpose)
Run **one** gunicorn worker and **one** instance. SQLite allows a single writer, and the login/check-in rate
limits are kept in memory. Scaling out would need Postgres and a shared limiter store (e.g. Redis).
The check-in limit is per IP and generous (60/min) because a whole classroom shares one Wi-Fi address.

### Backups
Back up the SQLite file (WAL mode: copy with `sqlite3 attendance.db ".backup backup.db"`).

## Operations (CLI)
| Command | Purpose |
|---|---|
| `flask init-platform-owner` | Create a platform owner. |
| `flask create-organisation` | Create an organisation + admin without the UI. |
| `flask delete-organisation <id>` | Permanently delete an organisation and **all** its data (CLI only, asks for the name). |
| `flask top-up-sessions` | Create upcoming sessions (daily). |
| `flask seed-demo` | Demo organisation, tutor, students, class. |

## Behaviour worth knowing
- **Daylight saving:** sessions are built from the local date + local time in the organisation's time zone and
  converted to UTC per date (never "+7 days in UTC"), so 19:00 stays 19:00 local. A time that doesn't exist
  (clocks forward) moves forward by the gap (01:30 → 02:30); an ambiguous time uses the first occurrence.
- **Schedule changes** affect only future sessions with no attendance. Past sessions are never touched.
- **Passwords:** argon2. Temporary passwords are shown once on screen; the app sends no email. Users must change
  them at first sign-in.
- **GDPR:** any tutor or admin can delete a student and all their attendance (confirmation required). The audit log
  stores only ids and status words, never names or emails. No automatic retention. Replace `PRIVACY_NOTICE`
  with your lawyer-approved text before going live.
- **Security:** CSRF on all forms, login rate limit, strict CSP (no inline scripts or styles), HttpOnly +
  SameSite cookies, `Secure` in production, tenant checks on every query (other organisations' and other
  tutors' records return 404).
- **Design:** Slate and mist tokens live in `app/static/css/tokens.css`. Inter is used if installed, otherwise the
  system font (no external font requests, which keeps the CSP strict).
- **One session cookie** is used for both school users and the platform owner (separate accounts and login pages).
