"""Cross-track error (XTE) of a GNSS track against an AB line.

An AB line is the straight guidance line a tractor follows: the operator
records point A and point B, the steering controller keeps the machine on
the line through them. XTE is the sideways distance from that line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .nmea import FIX_QUALITY, Fix

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class AbLine:
    a_lat: float
    a_lon: float
    b_lat: float
    b_lon: float

    @classmethod
    def from_heading(cls, lat: float, lon: float, heading_deg: float, length_m: float = 1000):
        """Line starting at A and running `length_m` along a compass heading."""
        north = length_m * math.cos(math.radians(heading_deg))
        east = length_m * math.sin(math.radians(heading_deg))
        b_lat = lat + math.degrees(north / EARTH_RADIUS_M)
        b_lon = lon + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
        return cls(lat, lon, b_lat, b_lon)

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        """Metres east / north of point A. A flat-earth approximation is
        accurate to millimetres over the few hundred metres of a field."""
        east = math.radians(lon - self.a_lon) * EARTH_RADIUS_M * math.cos(math.radians(self.a_lat))
        north = math.radians(lat - self.a_lat) * EARTH_RADIUS_M
        return east, north

    @property
    def heading_deg(self) -> float:
        east, north = self.to_local(self.b_lat, self.b_lon)
        return math.degrees(math.atan2(east, north)) % 360

    def cross_track_error(self, lat: float, lon: float) -> float:
        """Signed distance in metres, positive = right of the line (looking A to B)."""
        bx, by = self.to_local(self.b_lat, self.b_lon)
        px, py = self.to_local(lat, lon)
        return (bx * py - by * px) / -math.hypot(bx, by)


def ab_line_from_track(fixes: list[Fix], min_speed_mps: float = 0.5) -> AbLine:
    """Use the first and last moving fixes of a straight pass as A and B."""
    moving = [f for f in fixes if (f.speed_mps or 0) >= min_speed_mps] or fixes
    if len(moving) < 2:
        raise ValueError("need at least two fixes to define an AB line")
    a, b = moving[0], moving[-1]
    return AbLine(a.lat, a.lon, b.lat, b.lon)


def heading_deviation(course_deg: float, line_heading_deg: float) -> float:
    return abs((course_deg - line_heading_deg + 180) % 360 - 180)


@dataclass
class GuidanceResult:
    line: AbLine
    points: pd.DataFrame
    fix_class: str
    limit_m: float | None
    stats: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.limit_m is not None and self.stats["xte_p95_m"] <= self.limit_m


def evaluate_track(
    fixes: list[Fix],
    line: AbLine,
    classes: dict | None = None,
    min_speed_mps: float = 0.5,
    max_heading_dev_deg: float = 20,
) -> GuidanceResult:
    rows = []
    for f in fixes:
        east, north = line.to_local(f.lat, f.lon)
        moving = (f.speed_mps or 0) >= min_speed_mps
        on_line = f.course_deg is None or heading_deviation(f.course_deg, line.heading_deg) <= max_heading_dev_deg
        rows.append(
            {
                "time_s": f.time_s,
                "east_m": east,
                "north_m": north,
                "xte_m": line.cross_track_error(f.lat, f.lon),
                "quality": f.quality,
                "used": moving and on_line,
            }
        )
    points = pd.DataFrame(rows)
    used = points[points["used"]]
    if used.empty:
        raise ValueError("no fixes on the AB line (check speed and heading filters)")

    # The accuracy class is the worst fix quality used, so a pass that dropped
    # from RTK to plain GPS is judged against the GPS limit, not the RTK one.
    fix_class = FIX_QUALITY.get(int(used["quality"].min()), "GPS")
    limit = (classes or {}).get(fix_class, {}).get("xte_p95_m")
    xte = used["xte_m"].abs()
    stats = {
        "fixes_total": len(points),
        "fixes_used": len(used),
        "duration_s": round(float(used["time_s"].iloc[-1] - used["time_s"].iloc[0]), 1),
        "xte_mean_m": round(float(used["xte_m"].mean()), 3),
        "xte_rms_m": round(float(np.sqrt((used["xte_m"] ** 2).mean())), 3),
        "xte_p95_m": round(float(xte.quantile(0.95)), 3),
        "xte_max_m": round(float(xte.max()), 3),
    }
    return GuidanceResult(line, points, fix_class, limit, stats)


def plot_track(result: GuidanceResult, path: str | Path, title: str = "Guidance check") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts = result.points
    used = pts[pts["used"]]
    fig, (ax_map, ax_xte) = plt.subplots(1, 2, figsize=(11, 4.2))
    bx, by = result.line.to_local(result.line.b_lat, result.line.b_lon)
    ax_map.plot([0, bx], [0, by], "--", color="#888", label="AB line")
    ax_map.plot(pts["east_m"], pts["north_m"], ".", ms=3, color="#bbb", label="all fixes")
    ax_map.plot(used["east_m"], used["north_m"], ".", ms=4, color="#2e7d32", label="fixes used")
    ax_map.set(xlabel="east [m]", ylabel="north [m]", title="Track vs AB line")
    ax_map.axis("equal")
    ax_map.legend(fontsize=8)

    t0 = used["time_s"].iloc[0]
    ax_xte.plot(used["time_s"] - t0, used["xte_m"], color="#c62828")
    if result.limit_m:
        for sign in (1, -1):
            ax_xte.axhline(sign * result.limit_m, ls=":", color="#555")
    ax_xte.axhline(0, color="#888", lw=0.8)
    ax_xte.set(xlabel="time [s]", ylabel="cross-track error [m]", title=f"XTE ({result.fix_class})")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return Path(path)
