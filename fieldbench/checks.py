"""Test checks: each one looks at a decoded recording and returns pass/fail
with the expected and the measured value, the way a test report needs it."""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import Capture
from .spec import Spec


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    expected: str
    measured: str
    t_s: float | None = None  # where it failed, for the log excerpt

    def __post_init__(self):
        # pandas comparisons return numpy.bool_; keep plain Python types for JSON
        object.__setattr__(self, "passed", bool(self.passed))


def cycle_times(capture: Capture, spec: Spec) -> list[CheckResult]:
    results = []
    for m in spec.messages.values():
        diffs = capture.times(m.name).diff().dropna() * 1000
        low, high = m.cycle_ms * (1 - m.tolerance_pct / 100), m.cycle_ms * (1 + m.tolerance_pct / 100)
        if diffs.empty:
            results.append(CheckResult(f"cycle {m.name}", False, f"{low:.0f}-{high:.0f} ms", "no frames"))
            continue
        bad = diffs[(diffs < low) | (diffs > high)]
        t_fail = float(capture.times(m.name)[bad.index[0]]) if len(bad) else None
        measured = f"min {diffs.min():.1f} / mean {diffs.mean():.1f} / max {diffs.max():.1f} ms"
        results.append(CheckResult(f"cycle {m.name}", bad.empty, f"{low:.0f}-{high:.0f} ms", measured, t_fail))
    return results


def timeouts(capture: Capture, spec: Spec) -> list[CheckResult]:
    results = []
    for m in spec.messages.values():
        t = capture.times(m.name).reset_index(drop=True)
        diffs = t.diff() * 1000
        worst = float(diffs.max()) if len(t) > 1 else float("inf")
        t_fail = float(t[diffs.idxmax() - 1]) if worst > m.timeout_ms and len(t) > 1 else None
        results.append(
            CheckResult(
                f"timeout {m.name}",
                worst <= m.timeout_ms,
                f"gap <= {m.timeout_ms:.0f} ms",
                f"max gap {worst:.1f} ms",
                t_fail,
            )
        )
    return results


def signal_ranges(capture: Capture, spec: Spec) -> list[CheckResult]:
    results = []
    for s in spec.signals.values():
        series = capture.signal(s.name)
        outside = series[(series < s.min) | (series > s.max)]
        t_fail = float(outside.index[0]) if len(outside) else None
        results.append(
            CheckResult(
                f"range {s.name}",
                outside.empty,
                f"{s.min:g}..{s.max:g} {s.unit}",
                f"{series.min():g}..{series.max():g} {s.unit}",
                t_fail,
            )
        )
    return results


def reaction(
    capture: Capture, spec: Spec, signal: str, equals: float, after_s: float, within_ms: float
) -> list[CheckResult]:
    """The signal must reach `equals` no later than `within_ms` after `after_s`."""
    series = capture.signal(signal)
    hits = series[(series.index >= after_s) & (series == equals)]
    name = f"{signal} -> {equals:g} after {after_s:g} s"
    if hits.empty:
        return [CheckResult(name, False, f"<= {within_ms:g} ms", "never", after_s)]
    latency = (hits.index[0] - after_s) * 1000
    return [CheckResult(name, latency <= within_ms, f"<= {within_ms:g} ms", f"{latency:.0f} ms", float(hits.index[0]))]


def holds(capture: Capture, spec: Spec, signal: str, equals: float, from_s: float, to_s: float) -> list[CheckResult]:
    """The signal must stay at `equals` for the whole window."""
    series = capture.signal(signal)
    window = series[(series.index >= from_s) & (series.index <= to_s)]
    wrong = window[window != equals]
    name = f"{signal} == {equals:g} from {from_s:g} to {to_s:g} s"
    if wrong.empty:
        return [CheckResult(name, True, f"{equals:g}", f"{equals:g} ({len(window)} frames)")]
    t_fail = float(wrong.index[0])
    return [CheckResult(name, False, f"{equals:g}", f"{wrong.iloc[0]:g} at {t_fail:.2f} s", t_fail)]


def dtc_active(capture: Capture, spec: Spec, spn: int, fmi: int, after_s: float, within_ms: float) -> list[CheckResult]:
    """DM1 must report SPN/FMI no later than `within_ms` after `after_s`."""
    dm1 = capture.tables.get("DM1")
    name = f"DM1 SPN {spn} FMI {fmi}"
    if dm1 is None:
        return [CheckResult(name, False, f"<= {within_ms:g} ms", "no DM1 frames", after_s)]
    # J1939 SPN is 19 bits: 16 low bits + 3 high bits in a separate byte.
    dm1_spn = dm1["SpnLow"] + dm1["SpnHigh"] * 65536
    hits = dm1[(dm1["t"] >= after_s) & (dm1_spn == spn) & (dm1["Fmi"] == fmi)]
    if hits.empty:
        return [CheckResult(name, False, f"<= {within_ms:g} ms", "never", after_s)]
    latency = (hits["t"].iloc[0] - after_s) * 1000
    return [
        CheckResult(name, latency <= within_ms, f"<= {within_ms:g} ms", f"{latency:.0f} ms", float(hits["t"].iloc[0]))
    ]


def error_frames(capture: Capture, spec: Spec, min_count: int) -> list[CheckResult]:
    """Sanity check that the bus-error fault really happened."""
    n = capture.error_frames
    return [CheckResult("error frames injected", n >= min_count, f">= {min_count}", str(n))]


CHECKS = {
    "cycle_times": cycle_times,
    "timeouts": timeouts,
    "signal_ranges": signal_ranges,
    "reaction": reaction,
    "holds": holds,
    "dtc_active": dtc_active,
    "error_frames": error_frames,
}


def run_checks(check_specs: list[dict], capture: Capture, spec: Spec) -> list[CheckResult]:
    results = []
    for check in check_specs:
        params = dict(check)
        kind = params.pop("type")
        if kind not in CHECKS:
            raise ValueError(f"unknown check type {kind}")
        results.extend(CHECKS[kind](capture, spec, **params))
    return results
