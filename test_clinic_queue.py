from clinic_queue import ClinicQueue


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_patients_are_served_in_the_order_they_joined():
    queue = ClinicQueue()
    assert [queue.join(), queue.join(), queue.join()] == [1, 2, 3]

    assert queue.call_next() == 1
    assert queue.call_next() == 2
    assert queue.snapshot()["waiting"] == [3]


def test_next_on_an_empty_queue_finishes_the_current_patient():
    queue = ClinicQueue()
    queue.join()
    queue.call_next()

    assert queue.call_next() is None
    assert queue.snapshot()["serving"] is None


def test_estimate_uses_the_default_until_someone_has_been_seen():
    queue = ClinicQueue(default_minutes=5)
    state = queue.snapshot()
    assert state["minutes_per_patient"] == 5
    assert state["estimate_is_default"] is True


def test_estimate_is_the_average_of_recent_consultations():
    clock = FakeClock()
    queue = ClinicQueue(clock=clock, sample_size=2)
    for _ in range(4):
        queue.join()

    queue.call_next()          # patient 1 starts at t=0
    clock.now = 60
    queue.call_next()          # patient 1 took 1 min
    clock.now = 60 + 300
    queue.call_next()          # patient 2 took 5 min
    assert queue.minutes_per_patient() == 3

    clock.now = 360 + 420
    queue.call_next()          # patient 3 took 7 min; only the last 2 count
    assert queue.minutes_per_patient() == 6


def test_reset_starts_numbering_again():
    queue = ClinicQueue()
    queue.join()
    queue.join()
    queue.reset()

    assert queue.join() == 1
    assert queue.snapshot()["serving"] is None


def test_wait_for_change_returns_immediately_when_already_behind():
    queue = ClinicQueue()
    _, version = queue.wait_for_change(None, timeout=0)
    assert queue.wait_for_change(version, timeout=0) == (None, version)

    queue.join()
    snapshot, new_version = queue.wait_for_change(version, timeout=0)
    assert snapshot["waiting"] == [1]
    assert new_version != version
