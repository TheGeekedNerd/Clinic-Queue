# Clinic Queue

People lose whole days waiting in clinic queues. This is a virtual queue: patients take a number on their phone,
then see their place in line and an estimated wait, updating live, instead of standing in a line.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:STAFF_PIN = "2468"   # optional: without it, a random PIN is printed in the terminal
.venv\Scripts\python app.py
```

| Page | Address | Who it's for |
|---|---|---|
| Join the queue | http://localhost:5000/ | Patients (opened by the QR code) |
| Staff | http://localhost:5000/staff | Staff, after entering the PIN |
| Waiting-room screen | http://localhost:5000/display | A TV in the waiting room |
| Door poster | http://localhost:5000/poster | Print and stick on the clinic door |

To try it from a phone, connect it to the same Wi-Fi and open `http://<your-computer's-IP>:5000/`
(find the IP with `ipconfig`). Windows may ask to allow Python through the firewall. Allow it on private networks.

Tests: `.venv\Scripts\pip install pytest` then `.venv\Scripts\python -m pytest`.

## Settings

| Variable | What it does |
|---|---|
| `STAFF_PIN` | PIN for the staff page. If it isn't set when hosting, staff login is turned off. |
| `SECRET_KEY` | Signs the staff login cookie. Set it when hosting, or staff are logged out on every restart. |
| `DATABASE_PATH` | Where the SQLite file is stored. Default: `clinic_queue.db` next to `app.py`. |
| `PUBLIC_URL` | Address the QR codes point to. Default: worked out from the request. |

## How it works

- **The queue** ([clinic_queue.py](clinic_queue.py)) is a `collections.deque`: patients join at the back (`append`),
  staff take from the front (`popleft`).
- **Surviving crashes**: every change is written to SQLite before the in-memory queue changes. On startup, the queue
  is rebuilt from the database: tickets not yet called are waiting, and the one called but not finished is being seen.
- **Live updates** use Server-Sent Events. Every open page keeps a connection to `/events`, and the server pushes the
  new queue state the moment anything changes, so no page ever needs refreshing.
- **Wait estimate** = average time of the last 5 consultations × people ahead of you. Each consultation is timed
  from one "Next" press to the following one. Until anyone has been seen, it assumes 5 minutes per patient.
- **Staff PIN**: the staff page and the Next/Reset actions need a login. PINs are compared in constant time
  (`hmac.compare_digest`), and 5 wrong tries lock that IP address out for 5 minutes.
- **Alerts**: patients can tap "Notify me when I'm close" to get a phone notification when 2 people are ahead
  and again when it's their turn. This needs HTTPS and the page left open in the background.
- **QR code**: `/poster` and `/display` show a QR code that opens the join page. If you open them via `localhost`,
  they swap in this computer's network IP, because a code pointing to `localhost` would send each phone to itself.
- A cookie remembers each phone's ticket, so refreshing or tapping "Join" twice doesn't take a second number.

## Hosting on Render

- Start command: `gunicorn --worker-class gthread --workers 1 --threads 100 app:app`. It must be one worker:
  the live updates rely on all requests sharing one in-memory queue.
- Set `STAFF_PIN` and `SECRET_KEY` under **Environment**.

## Limits (for now)

- On Render's free plan the disk is wiped when the app sleeps or redeploys, so the queue only survives crashes
  and restarts. Keeping it through those needs a persistent disk (paid) or a hosted database such as Postgres.
- Alerts stop if the patient closes the tab. Alerts with the tab closed would need Web Push or SMS.
- On iPhone, alerts only work after adding the page to the Home Screen (an iOS restriction).
