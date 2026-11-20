import pytest

from fieldbench.analysis import (
    asc_excerpt,
    dbc_cycle_times,
    decode,
    find_dropouts,
    message_stats,
    plot_signals,
    read_log,
    write_logs,
)
from fieldbench.bench import simulate
from fieldbench.ecus import RELEASES


@pytest.mark.parametrize("suffix", [".blf", ".asc"])
def test_log_roundtrip(tmp_path, nominal_messages, db, suffix):
    blf, asc = write_logs(nominal_messages, tmp_path / "run_1.4.0")
    assert blf.name == "run_1.4.0.blf" and asc.name == "run_1.4.0.asc"
    back = read_log(blf if suffix == ".blf" else asc)
    assert len(back) == len(nominal_messages)
    original = decode(nominal_messages, db).signal("EngineSpeed")
    restored = decode(back, db).signal("EngineSpeed")
    assert list(restored.values) == list(original.values)


def test_find_dropouts_on_gnss_dropout(scenario, db):
    fault = {"type": "gnss_dropout", "at_s": 6.0, "duration_s": 2.0}
    capture = decode(simulate(scenario, RELEASES["1.4.0"], [fault], db), db)
    dropouts = find_dropouts(capture, dbc_cycle_times(db))
    assert {d.message for d in dropouts} == {"GNSS_POSITION", "GNSS_COG_SOG"}
    gnss = next(d for d in dropouts if d.message == "GNSS_POSITION")
    assert gnss.gap_ms == pytest.approx(2100, abs=5)


def test_no_dropouts_in_nominal_pass(nominal_messages, db):
    capture = decode(nominal_messages, db)
    assert find_dropouts(capture, dbc_cycle_times(db)) == []
    stats = message_stats(capture, dbc_cycle_times(db)).set_index("message")
    assert stats.loc["EEC1", "mean_ms"] == pytest.approx(20, abs=0.5)


def test_unknown_frames_and_error_frames_are_kept(nominal_messages, db):
    import can

    extra = [can.Message(arbitration_id=0x123, data=[1]), can.Message(is_error_frame=True)]
    capture = decode(nominal_messages[:10] + extra, db)
    assert "0x123" in set(capture.frames["name"])
    assert capture.error_frames == 1
    with pytest.raises(KeyError):
        capture.signal("NoSuchSignal")


def test_asc_excerpt_is_decoded(nominal_messages, db):
    import can

    msgs = [
        *nominal_messages,
        can.Message(timestamp=5.0005, is_error_frame=True),
        can.Message(timestamp=5.001, arbitration_id=0x7),
    ]
    text = asc_excerpt(sorted(msgs, key=lambda m: m.timestamp), db, 5.0, 5.11, limit=100)
    assert "// GUIDANCE_STATUS SteeringEngaged=1" in text
    assert "ErrorFrame" in text
    assert asc_excerpt(nominal_messages, db, 0, 14, limit=5).endswith("...")


def test_plot_signals(tmp_path, nominal_messages, db):
    capture = decode(nominal_messages, db)
    path = plot_signals(capture, ["EngineSpeed", "NotThere"], tmp_path / "p.png", spans=[(1, 2, "x")], title="t")
    assert path.stat().st_size > 1000
