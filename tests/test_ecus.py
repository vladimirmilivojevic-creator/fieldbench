"""Unit tests of the guidance state machine and the seeded defects."""

import random

import pytest

from fieldbench.ecus import (
    EXIT_GNSS_LOST,
    EXIT_SPEED_LOST,
    EXIT_SPEED_RANGE,
    RELEASES,
    GuidanceController,
    TractorEcu,
)
from fieldbench.plant import Plant


def controller(db, scenario, release="1.4.0"):
    return GuidanceController(db, RELEASES[release], scenario, random.Random(1))


def feed(ctrl, t_ms, speed=2.5, gnss=True, wheel=True):
    if gnss:
        ctrl.receive("GNSS_POSITION", {"Latitude": 48.1725, "Longitude": 14.5113}, t_ms)
    if wheel:
        ctrl.receive("WBSD", {"WheelBasedSpeed": speed}, t_ms)
    ctrl.update(t_ms)


def engaged_controller(db, scenario, release="1.4.0"):
    ctrl = controller(db, scenario, release)
    for t in range(0, ctrl.engage_at_ms + 200, 100):
        feed(ctrl, t)
    assert ctrl.engaged
    return ctrl


def test_not_engaged_without_operator_request(db, scenario):
    ctrl = controller(db, scenario)
    feed(ctrl, 1000)
    assert ctrl.ready and not ctrl.engaged


def test_gnss_timeout_disengages_with_reason_and_dtc(db, scenario):
    ctrl = engaged_controller(db, scenario)
    last = ctrl.engage_at_ms + 100
    feed(ctrl, last + 300, gnss=False)  # exactly at the timeout: still fine
    assert ctrl.engaged
    feed(ctrl, last + 305, gnss=False)
    assert not ctrl.engaged
    assert ctrl.exit_reason == EXIT_GNSS_LOST
    assert ctrl.dtc_active
    dm1 = ctrl.values("DM1", None, 0)
    assert (dm1["SpnLow"], dm1["Fmi"], dm1["AmberWarningLamp"]) == (584, 9, 1)


def test_wheel_speed_timeout_reason(db, scenario):
    ctrl = engaged_controller(db, scenario)
    feed(ctrl, ctrl.engage_at_ms + 500, wheel=False)
    assert ctrl.exit_reason == EXIT_SPEED_LOST


def test_speed_out_of_range_reason(db, scenario):
    ctrl = engaged_controller(db, scenario)
    feed(ctrl, ctrl.engage_at_ms + 200, speed=20)
    assert ctrl.exit_reason == EXIT_SPEED_RANGE


@pytest.mark.parametrize(("release", "re_engages"), [("1.3.0", True), ("1.4.0", False)])
def test_re_engage_after_gnss_returns(db, scenario, release, re_engages):
    ctrl = engaged_controller(db, scenario, release)
    t = ctrl.engage_at_ms + 1000
    feed(ctrl, t, gnss=False, wheel=True)
    assert not ctrl.engaged
    feed(ctrl, t + 100)  # GNSS is back, operator did nothing
    assert ctrl.engaged is re_engages


@pytest.mark.parametrize(("release", "position"), [("1.3.0", 102.0), ("1.4.0", 100.0)])
def test_hitch_position_clamp(db, scenario, release, position):
    ecu = TractorEcu(db, RELEASES[release], scenario, random.Random(1))
    state = Plant(scenario).state(scenario.duration_s)
    assert ecu.values("RHS", state, 0)["RearHitchPosition"] == position


def test_dm1_event_frame_on_dtc_change(db, scenario):
    ctrl = engaged_controller(db, scenario)
    ctrl._next_ms = dict.fromkeys(ctrl.periods_ms, 99_999)  # nothing periodic is due
    feed(ctrl, 2600, gnss=False)
    frames = ctrl.send(2600, Plant(scenario).state(2.6))
    assert [db.get_message_by_frame_id(f.arbitration_id).name for f in frames] == ["DM1"]
    assert ctrl.send(2605, Plant(scenario).state(2.6)) == []  # sent once per change
