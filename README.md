# Clinic Queue

People lose whole days waiting in clinic queues. This is a virtual queue: patients take a number on their phone,
then see their place in line and an estimated wait, updating live, instead of standing in a line.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

- Patient page: http://localhost:5000/
- Staff page: http://localhost:5000/staff
- Door poster with QR code: http://localhost:5000/poster (also linked from the staff page)

To try it from a phone, connect it to the same Wi-Fi and open `http://<your-computer's-IP>:5000/`
(find the IP with `ipconfig`). Windows may ask to allow Python through the firewall. Allow it on private networks.

Tests: `.venv\Scripts\pip install pytest` then `.venv\Scripts\python -m pytest`.

## How it works

- **The queue** ([clinic_queue.py](clinic_queue.py)) is a `collections.deque`: patients join at the back (`append`),
  staff take from the front (`popleft`).
- **Live updates** use Server-Sent Events. Every open page keeps a connection to `/events`, and the server pushes the
  new queue state the moment anything changes, so no page ever needs refreshing.
- **Wait estimate** = average time of the last 5 consultations × people ahead of you. Each consultation is timed
  from one "Next" press to the following one. Until anyone has been seen, it assumes 5 minutes per patient.
- **QR code**: `/poster` is a printable A4 sign whose QR code opens the join page. If you open it via `localhost`,
  it swaps in this computer's network IP, because a code pointing to `localhost` would send each phone to itself.
  Once the app is hosted online, set `PUBLIC_URL` (e.g. `$env:PUBLIC_URL="https://myclinic.example.com"`) and the
  code will point to that address instead.
- A cookie remembers each phone's ticket, so refreshing or tapping "Join" twice doesn't take a second number.

## Limits (for now)

- The queue lives in memory, so restarting the server clears it.
- The staff page has no login.
