import json
import os
import socket

import qrcode
import qrcode.image.svg
from flask import Flask, Response, jsonify, make_response, redirect, render_template, request, url_for
from markupsafe import Markup

from clinic_queue import ClinicQueue

app = Flask(__name__)
queue = ClinicQueue()


def _lan_ip():
    """This computer's address on the local network, e.g. 192.168.1.20."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it just picks the outgoing interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _join_url():
    """The address patients' phones should open. Set PUBLIC_URL once the app is hosted online."""
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


def _active_ticket():
    """The ticket stored in this phone's cookie, if it is still waiting or being served."""
    ticket = request.cookies.get("ticket", type=int)
    state = queue.snapshot()
    if ticket is not None and (ticket == state["serving"] or ticket in state["waiting"]):
        return ticket
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
    response.set_cookie("ticket", str(ticket), max_age=12 * 60 * 60, samesite="Lax")
    return response


@app.get("/ticket/<int:number>")
def ticket_page(number):
    return render_template("ticket.html", number=number)


@app.get("/staff")
def staff_page():
    return render_template("staff.html")


@app.get("/poster")
def poster_page():
    """A printable sign for the clinic door with a QR code that opens the join page."""
    url = _join_url()
    return render_template("poster.html", url=url, qr_svg=Markup(_qr_svg(url)))


@app.get("/qr.svg")
def qr_image():
    return Response(_qr_svg(_join_url()), mimetype="image/svg+xml")


@app.post("/api/next")
def call_next():
    queue.call_next()
    return jsonify(queue.snapshot())


@app.post("/api/reset")
def reset():
    queue.reset()
    return jsonify(queue.snapshot())


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
    # host 0.0.0.0 so phones on the same Wi-Fi can reach it; threaded so live connections don't block.
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
