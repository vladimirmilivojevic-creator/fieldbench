import pandas as pd
import pytest

from fieldbench.analysis import Capture, decode
from fieldbench.bench import simulate
from fieldbench.checks import dtc_active, error_frames, holds, reaction, run_checks, timeouts
from fieldbench.ecus import RELEASES


@pytest.fixture(scope="module")
def capture(nominal_messages, db):
    return decode(nominal_messages, db)


def test_nominal_pass_meets_communication_spec(capture, spec):
    results = run_checks([{"type": "cycle_times"}, {"type": "timeouts"}, {"type": "signal_ranges"}], capture, spec)
    assert len(results) == 2 * len(spec.messages) + len(spec.signals)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_release_130_defects_are_found(scenario, db, spec):
    cap = decode(simulate(scenario, RELEASES["1.3.0"], [], db), db)
    failed = {
        r.name for r in run_checks([{"type": "cycle_times"}, {"type": "signal_ranges"}], cap, spec) if not r.passed
    }
    assert failed == {"cycle GNSS_COG_SOG", "range RearHitchPosition"}


def test_reaction_latency(capture, spec):
    [ok] = reaction(capture, spec, "SteeringEngaged", 1, after_s=2.0, within_ms=300)
    assert ok.passed and ok.measured.endswith("ms")
    [never] = reaction(capture, spec, "SteeringEngaged", 2, after_s=0, within_ms=300)
    assert not never.passed and never.measured == "never"
    [late] = reaction(capture, spec, "SteeringEngaged", 1, after_s=1.0, within_ms=100)
    assert not late.passed


def test_holds_reports_first_wrong_value(capture, spec):
    [bad] = holds(capture, spec, "SteeringEngaged", 0, from_s=0, to_s=5)
    assert not bad.passed and bad.t_s == pytest.approx(2.0, abs=0.11)


def test_dtc_and_timeouts_after_gnss_dropout(scenario, db, spec):
    fault = {"type": "gnss_dropout", "at_s": 6.0, "duration_s": 2.0}
    cap = decode(simulate(scenario, RELEASES["1.4.0"], [fault], db), db)
    [dtc] = dtc_active(cap, spec, 584, 9, after_s=6.0, within_ms=1000)
    assert dtc.passed
    [wrong] = dtc_active(cap, spec, 190, 2, after_s=6.0, within_ms=1000)
    assert not wrong.passed
    failed = {r.name for r in timeouts(cap, spec) if not r.passed}
    assert failed == {"timeout GNSS_POSITION", "timeout GNSS_COG_SOG"}


def test_checks_on_empty_capture(spec):
    empty = Capture(pd.DataFrame(columns=["t", "name", "arbitration_id", "error"]), {})
    assert not dtc_active(empty, spec, 584, 9, 0, 100)[0].passed
    assert not error_frames(empty, spec, 1)[0].passed
    assert all(not r.passed for r in run_checks([{"type": "cycle_times"}], empty, spec))


def test_unknown_check_type(capture, spec):
    with pytest.raises(ValueError):
        run_checks([{"type": "vibes"}], capture, spec)
