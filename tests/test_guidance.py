import math

import pytest

from fieldbench.guidance import AbLine, ab_line_from_track, evaluate_track, heading_deviation, plot_track
from fieldbench.nmea import Fix

LAT, LON = 48.17, 14.51
CLASSES = {"RTK": {"xte_p95_m": 0.025}, "GPS": {"xte_p95_m": 1.5}}


def offset(line: AbLine, along_m: float, right_m: float) -> tuple[float, float]:
    """Point `along_m` down the line and `right_m` to its right."""
    h = math.radians(line.heading_deg)
    north = along_m * math.cos(h) - right_m * math.sin(h)
    east = along_m * math.sin(h) + right_m * math.cos(h)
    lat = line.a_lat + math.degrees(north / 6_371_000)
    lon = line.a_lon + math.degrees(east / (6_371_000 * math.cos(math.radians(line.a_lat))))
    return lat, lon


def test_xte_sign_and_size_on_north_line():
    line = AbLine.from_heading(LAT, LON, 0)
    assert line.heading_deg == pytest.approx(0, abs=1e-6)
    assert line.cross_track_error(*offset(line, 50, 2.0)) == pytest.approx(2.0, abs=1e-3)
    assert line.cross_track_error(*offset(line, 50, -0.5)) == pytest.approx(-0.5, abs=1e-3)


@pytest.mark.parametrize("heading", [0, 72, 180, 233.8, 359])
def test_from_heading_roundtrip(heading):
    line = AbLine.from_heading(LAT, LON, heading)
    assert heading_deviation(line.heading_deg, heading) < 0.01
    assert line.cross_track_error(*offset(line, 120, 0.3)) == pytest.approx(0.3, abs=1e-3)


def test_heading_deviation_wraps():
    assert heading_deviation(359, 1) == pytest.approx(2)
    assert heading_deviation(90, 270) == pytest.approx(180)


def make_track(line, right_m, quality=4, n=60):
    fixes = []
    for i in range(n):
        lat, lon = offset(line, i * 2.5, right_m(i))
        fixes.append(Fix(i, lat, lon, quality, 12, 0.7, 2.5, line.heading_deg))
    return fixes


def test_rtk_track_within_class_passes():
    line = AbLine.from_heading(LAT, LON, 72)
    result = evaluate_track(make_track(line, lambda i: 0.01 * math.sin(i)), line, CLASSES)
    assert result.fix_class == "RTK"
    assert result.passed
    assert result.stats["xte_max_m"] <= 0.011


def test_worst_fix_quality_sets_the_class():
    line = AbLine.from_heading(LAT, LON, 72)
    fixes = make_track(line, lambda i: 0.05)
    fixes[10].quality = 1  # one plain GPS fix in the pass
    result = evaluate_track(fixes, line, CLASSES)
    assert result.fix_class == "GPS"
    assert result.limit_m == 1.5


def test_filters_standstill_and_turns():
    line = AbLine.from_heading(LAT, LON, 0)
    fixes = make_track(line, lambda i: 0.0)
    fixes[0].speed_mps = 0.0
    fixes[1].course_deg = 180  # headland turn
    result = evaluate_track(fixes, line, CLASSES)
    assert result.stats["fixes_used"] == len(fixes) - 2


def test_no_usable_fixes_raises():
    line = AbLine.from_heading(LAT, LON, 0)
    fixes = make_track(line, lambda i: 0.0, n=3)
    for f in fixes:
        f.speed_mps = 0
    with pytest.raises(ValueError):
        evaluate_track(fixes, line, CLASSES)


def test_ab_line_from_track():
    line = AbLine.from_heading(LAT, LON, 45)
    derived = ab_line_from_track(make_track(line, lambda i: 0.0))
    assert heading_deviation(derived.heading_deg, 45) < 0.1
    with pytest.raises(ValueError):
        ab_line_from_track(make_track(line, lambda i: 0.0, n=1))


def test_unknown_class_has_no_limit():
    line = AbLine.from_heading(LAT, LON, 0)
    result = evaluate_track(make_track(line, lambda i: 0.0), line, {})
    assert result.limit_m is None and not result.passed


def test_plot_track(tmp_path):
    line = AbLine.from_heading(LAT, LON, 10)
    result = evaluate_track(make_track(line, lambda i: 0.01), line, CLASSES)
    assert plot_track(result, tmp_path / "xte.png").stat().st_size > 1000
