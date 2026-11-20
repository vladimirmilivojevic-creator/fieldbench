from collections import Counter

import pytest

from fieldbench.analysis import decode
from fieldbench.bench import Bench, BenchConfig, simulate
from fieldbench.ecus import RELEASES, build_ecus
from fieldbench.faults import FaultInjector
from fieldbench.plant import Plant


def counts(messages, db):
    return Counter("ERROR" if m.is_error_frame else db.get_message_by_frame_id(m.arbitration_id).name for m in messages)


def test_nominal_frame_counts_match_cycle_times(nominal_messages, db, scenario):
    c = counts(nominal_messages, db)
    duration_ms = scenario.duration_s * 1000
    assert c["EEC1"] == duration_ms / 20 + 1
    assert c["WBSD"] == c["RHS"] == c["GNSS_POSITION"] == c["GUIDANCE_STATUS"] == duration_ms / 100 + 1
    assert c["DM1"] == 15
    assert "ERROR" not in c


def test_frames_are_time_ordered_29_bit(nominal_messages):
    times = [m.timestamp for m in nominal_messages]
    assert times == sorted(times)
    assert all(m.is_extended_id for m in nominal_messages)


def test_runs_are_reproducible(scenario, db, nominal_messages):
    again = simulate(scenario, RELEASES["1.4.0"], [], db)
    assert [(m.timestamp, bytes(m.data)) for m in again] == [(m.timestamp, bytes(m.data)) for m in nominal_messages]


def test_steering_engages_after_operator_request(nominal_messages, db):
    engaged = decode(nominal_messages, db).signal("SteeringEngaged")
    assert engaged[engaged.index < 1.95].max() == 0
    assert engaged[engaged.index > 2.2].min() == 1


def test_drop_fault_removes_frames(scenario, db, nominal_messages):
    msgs = simulate(scenario, RELEASES["1.4.0"], [{"type": "drop", "message": "WBSD", "at_s": 5, "duration_s": 1}], db)
    assert counts(nominal_messages, db)["WBSD"] - counts(msgs, db)["WBSD"] == 10


def test_bus_off_silences_one_ecu(scenario, db):
    msgs = simulate(scenario, RELEASES["1.4.0"], [{"type": "bus_off", "ecu": "TECU", "at_s": 0, "duration_s": 99}], db)
    c = counts(msgs, db)
    assert c["WBSD"] == c["RHS"] == 0
    assert c["EEC1"] > 0


def test_bus_errors_inject_error_frames_and_retransmit(scenario, db, nominal_messages):
    fault = {"type": "bus_errors", "at_s": 4, "duration_s": 2, "rate_per_s": 100}
    msgs = simulate(scenario, RELEASES["1.4.0"], [fault], db)
    c = counts(msgs, db)
    assert 150 <= c["ERROR"] <= 200  # bursts can only hit frames that are really sent
    assert c["EEC1"] == counts(nominal_messages, db)["EEC1"]  # every frame got through on retry


def test_unknown_fault_type_is_rejected():
    with pytest.raises(ValueError, match="unknown fault"):
        FaultInjector([{"type": "solar_flare", "at_s": 0, "duration_s": 1}])


def test_bench_on_named_channel(scenario, db):
    ecus = build_ecus(db, RELEASES["1.4.0"], scenario)
    bench = Bench(db, ecus, Plant(scenario), FaultInjector(), BenchConfig(channel="named-test-channel"))
    assert len(bench.run(0.5)) > 20


def test_plant_profile(scenario):
    plant = Plant(scenario)
    assert plant.speed(0) == 0
    assert plant.speed(10) == pytest.approx(scenario.speed_kmh / 3.6)
    assert plant.distance(10) > plant.distance(5) > 0
    assert plant.hitch(0) == 80
    assert plant.hitch(5) == pytest.approx(20)
    assert plant.hitch(scenario.duration_s) > 100  # sensor overshoot at the end stop
