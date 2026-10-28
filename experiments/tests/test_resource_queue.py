import threading
import time

import pytest

from memweave_eval.paired import ResourcePool


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_fitting_pair_can_pass_blocked_head_without_overbooking(axis):
    pool = ResourcePool((10, 10, 10))
    initial = [0, 0, 0]
    initial[axis] = 6
    heavy = [1, 1, 1]
    heavy[axis] = 8
    light = [1, 1, 1]
    light[axis] = 4
    pool.acquire(initial, lambda: False)
    stop = threading.Event()
    light_started, release_light, heavy_started = (threading.Event() for _ in range(3))
    errors = []

    def work(weight, entered, release=None):
        try:
            pool.acquire(weight, stop.is_set)
            entered.set()
            if release:
                release.wait(2)
            pool.release(weight)
        except TimeoutError:
            pass
        except Exception as exc:  # noqa: BLE001 -- return thread failures to the test.
            errors.append(exc)

    first = threading.Thread(target=work, args=(heavy, heavy_started))
    second = threading.Thread(target=work, args=(light, light_started, release_light))
    first.start()
    until = time.monotonic() + 2
    while not pool.waiting and time.monotonic() < until:
        time.sleep(0.005)
    assert pool.waiting
    second.start()
    try:
        assert light_started.wait(1), "a waiting large pair must not block a fitting pair"
        assert not heavy_started.is_set()
        assert all(u <= c for u, c in zip(pool.used, pool.limits, strict=True))
        release_light.set()
        second.join(timeout=2)
        pool.release(initial)
        assert heavy_started.wait(1)
    finally:
        release_light.set()
        stop.set()
        with pool.condition:
            pool.condition.notify_all()
        first.join(timeout=2)
        second.join(timeout=2)
    assert not errors and not first.is_alive() and not second.is_alive()
    assert pool.used == [0, 0, 0]
