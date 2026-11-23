"""Inbound webhooks. Machine-to-machine, so exempt from CSRF (no browser session involved)."""
import re
import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..extensions import csrf

bp = Blueprint("hooks", __name__, url_prefix="/hooks")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUIRED = ("name", "email", "nationality")

# Per-day sequence for the NNNN part. In-memory: resets on restart, not shared between workers.
_lock = threading.Lock()
_counters: dict[str, int] = {}


def _next_reference() -> str | None:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with _lock:
        n = _counters.get(day, 0) + 1
        if n > 9999:
            return None
        _counters.clear()  # keep only today's counter
        _counters[day] = n
    return f"CB-{day}-{n:04d}"


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@bp.post("/signup")
@csrf.exempt
def signup():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object.")

    values = {k: data.get(k) for k in REQUIRED}
    missing = [k for k, v in values.items() if not isinstance(v, str) or not v.strip()]
    if missing:
        return _error("Missing or empty field(s): " + ", ".join(missing) + ".")

    email = values["email"].strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return _error("Email address is not well-formed.")

    reference = _next_reference()
    if reference is None:
        return _error("No more references available today.", 503)
    return jsonify({"reference": reference}), 200
