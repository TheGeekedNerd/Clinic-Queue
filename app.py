import hmac
import json
import os
import secrets
import socket
import threading
import time
from datetime import timedelta
from functools import wraps

import qrcode
import qrcode.image.svg
from flask import (Flask, Response, jsonify, make_response, redirect, render_template, request, session,
                   url_for)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

from clinic_queue import ClinicQueue

app = Flask(__name__)
app.config.update(
    # Signs the staff login cookie. Set SECRET_KEY when hosting, or staff are logged out on every restart.
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
# When hosted (e.g. on Render), a proxy handles HTTPS and forwards plain HTTP to us.
# Trust its headers so generated links use the real https:// address and we see each visitor's real IP.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
queue = ClinicQueue(os.environ.get("DATABASE_PATH", os.path.join(app.root_path, "clinic_queue.db")))


# --- Staff login -------------------------------------------------------------------------------

MAX_PIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60
_failed_logins = {}  # IP address -> (failed attempts, time of the latest one)
_failed_logins_lock = threading.Lock()


def _staff_pin():
    return os.environ.get("STAFF_PIN", "")


def _locked_out(ip):
    with _failed_logins_lock:
        failures, last = _failed_logins.get(ip, (0, 0.0))
        if time.time() - last > LOCKOUT_SECONDS:
            _failed_logins.pop(ip, None)
            return False
        return failures >= MAX_PIN_ATTEMPTS


def _record_failed_login(ip):
    with _failed_logins_lock:
        failures, last = _failed_logins.get(ip, (0, 0.0))
        if time.time() - last > LOCKOUT_SECONDS:
            failures = 0
        _failed_logins[ip] = (failures + 1, time.time())


def staff_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("staff"):
            if request.path.startswith("/api/"):
                return jsonify(error="Staff login required"), 401
            return redirect(url_for("staff_login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    pin = _staff_pin()
    error = None
    if request.method == "POST":
        ip = request.remote_addr
        if not pin:
            error = "Staff login is turned off until the STAFF_PIN setting is set."
        elif _locked_out(ip):
            error = "Too many wrong PINs. Try again in a few minutes."
        # compare_digest takes the same time however many digits match, so the PIN can't be guessed by timing.
        elif hmac.compare_digest(request.form.get("pin", "").encode(), pin.encode()):
            with _failed_logins_lock:
                _failed_logins.pop(ip, None)
            session.clear()
            session["staff"] = True
            session.permanent = True
            return redirect(url_for("staff_page"))
        else:
            _record_failed_login(ip)
            error = "Wrong PIN."
    return render_template("login.html", error=error, disabled=not pin)


@app.post("/staff/logout")
def staff_logout():
    session.clear()
    return redirect(url_for("staff_login"))


# --- QR code -----------------------------------------------------------------------------------

def _lan_ip():
    """This computer's address on the local network, e.g. 192.168.1.20."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it just picks the outgoing interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _join_url():
    """The address patients' phones should open. Set PUBLIC_URL to override it."""
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/") + "/"
    host = request.host
    hostname, _, port = host.partition(":")
    if hostname in ("localhost", "127.0.0.1"):
        # A QR code pointing at "localhost" would send each phone to itself.
        host = _lan_ip() + (f":{port}" if port else "")
    return f"{request.scheme}://{host}{url_for('join_page')}"


def _qr_svg(data):
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, border=0)
    return image.to_string(encoding="unicode")


# --- Patient pages -----------------------------------------------------------------------------

def _active_ticket():
    """The ticket stored in this phone's cookie, if it is still waiting or being served."""
    queue_id, _, number = request.cookies.get("ticket", "").partition(":")
    state = queue.snapshot()
    if queue_id != state["queue_id"] or not number.isdigit():
        return None
    number = int(number)
    if number == state["serving"] or number in state["waiting"]:
        return number
    return None


@app.get("/")
def join_page():
    ticket = _active_ticket()
    if ticket is not None:
        return redirect(url_for("ticket_page", number=ticket))
    return render_template("join.html")


@app.post("/join")
def join():
    # Stop a double tap or a back-and-resubmit from taking a second number.
    ticket = _active_ticket() or queue.join()
    response = make_response(redirect(url_for("ticket_page", number=ticket)))
    cookie = f"{queue.snapshot()['queue_id']}:{ticket}"
    response.set_cookie("ticket", cookie, max_age=12 * 60 * 60, samesite="Lax", httponly=True)
    return response


@app.get("/ticket/<int:number>")
def ticket_page(number):
    return render_template("ticket.html", number=number)


@app.get("/sw.js")
def service_worker():
    # Android Chrome only shows notifications through a service worker.
    response = app.send_static_file("sw.js")
    response.headers["Cache-Control"] = "no-cache"
    return response


# --- Public screens ----------------------------------------------------------------------------

@app.get("/display")
def display_page():
    """Full-screen view for a TV in the waiting room."""
    url = _join_url()
    return render_template("display.html", url=url, qr_svg=Markup(_qr_svg(url)))


@app.get("/poster")
def poster_page():
    """A printable sign for the clinic door with a QR code that opens the join page."""
    url = _join_url()
    return render_template("poster.html", url=url, qr_svg=Markup(_qr_svg(url)))


@app.get("/qr.svg")
def qr_image():
    return Response(_qr_svg(_join_url()), mimetype="image/svg+xml")


# --- Staff -------------------------------------------------------------------------------------

@app.get("/staff")
@staff_required
def staff_page():
    return render_template("staff.html")


@app.post("/api/next")
@staff_required
def call_next():
    queue.call_next()
    return jsonify(queue.snapshot())


@app.post("/api/reset")
@staff_required
def reset():
    queue.reset()
    return jsonify(queue.snapshot())


# --- Live updates ------------------------------------------------------------------------------

@app.get("/api/state")
def state():
    return jsonify(queue.snapshot())


@app.get("/events")
def events():
    """Server-Sent Events: push the queue state to every open page whenever it changes."""

    def stream():
        version = None  # forces the current state to be sent straight away
        while True:
            snapshot, version = queue.wait_for_change(version, timeout=15)
            if snapshot is None:
                yield ": keep-alive\n\n"  # stops proxies and phones from dropping an idle connection
            else:
                yield f"data: {json.dumps(snapshot)}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # Local runs: make up a PIN and secret if none were set. They go in the environment so the
    # debug reloader's restarted process keeps the same ones.
    if not _staff_pin():
        os.environ["STAFF_PIN"] = f"{secrets.randbelow(10**6):06d}"
        print(f" * Staff PIN: {os.environ['STAFF_PIN']}  (set STAFF_PIN to choose your own)")
    os.environ.setdefault("SECRET_KEY", app.config["SECRET_KEY"])
    # host 0.0.0.0 so phones on the same Wi-Fi can reach it; threaded so live connections don't block.
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
