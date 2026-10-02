import os

os.environ["DATABASE_PATH"] = ":memory:"  # must be set before the app module creates its queue

import pytest

import app as clinic


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STAFF_PIN", "4321")
    clinic.queue.reset()
    clinic._failed_logins.clear()
    return clinic.app.test_client()


def log_in(client, pin="4321"):
    return client.post("/staff/login", data={"pin": pin})


def test_staff_pages_need_a_login(client):
    assert client.get("/staff").headers["Location"].endswith("/staff/login")
    assert client.post("/api/next").status_code == 401
    assert client.post("/api/reset").status_code == 401


def test_correct_pin_lets_staff_call_the_next_patient(client):
    client.post("/join")
    assert log_in(client).headers["Location"].endswith("/staff")
    assert client.get("/staff").status_code == 200
    assert client.post("/api/next").get_json()["serving"] == 1


def test_wrong_pin_is_rejected(client):
    assert b"Wrong PIN" in log_in(client, "0000").data
    assert client.post("/api/next").status_code == 401


def test_too_many_wrong_pins_locks_out_even_the_right_one(client):
    for _ in range(clinic.MAX_PIN_ATTEMPTS):
        log_in(client, "0000")
    response = log_in(client)
    assert b"Too many wrong PINs" in response.data
    assert client.post("/api/next").status_code == 401


def test_logging_out_removes_access(client):
    log_in(client)
    client.post("/staff/logout")
    assert client.post("/api/next").status_code == 401


def test_login_is_off_when_no_pin_is_set(client, monkeypatch):
    monkeypatch.delenv("STAFF_PIN")
    assert b"turned off" in log_in(client, "").data


def test_public_pages_stay_open(client):
    for path in ("/", "/display", "/poster", "/sw.js", "/api/state"):
        assert client.get(path).status_code == 200, path
