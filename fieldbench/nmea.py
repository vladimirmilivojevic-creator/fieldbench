"""Read GNSS fixes from NMEA 0183 text: a log file or a live serial port.

Only the two sentences a guidance check needs are parsed:
GGA (position + fix quality) and RMC (speed + course).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

import serial

KNOTS_TO_MPS = 0.514444
FIX_QUALITY = {0: "none", 1: "GPS", 2: "DGPS", 4: "RTK", 5: "RTK float"}


@dataclass
class Fix:
    time_s: float  # seconds since midnight UTC
    lat: float
    lon: float
    quality: int = 1
    satellites: int = 0
    hdop: float = 0.0
    speed_mps: float | None = None
    course_deg: float | None = None


def checksum_ok(sentence: str) -> bool:
    """NMEA checksum: XOR of all characters between '$' and '*'."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, given = sentence[1:].partition("*")
    calculated = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    try:
        return calculated == int(given[:2], 16)
    except ValueError:
        return False


def _time_s(hhmmss: str) -> float:
    return int(hhmmss[0:2]) * 3600 + int(hhmmss[2:4]) * 60 + float(hhmmss[4:])


def _degrees(value: str, hemisphere: str) -> float:
    """ddmm.mmmm / dddmm.mmmm -> signed decimal degrees."""
    dot = value.index(".")
    degrees = float(value[: dot - 2]) + float(value[dot - 2 :]) / 60
    return -degrees if hemisphere in ("S", "W") else degrees


def parse_sentence(line: str) -> tuple[str, dict] | None:
    """Return ("GGA" | "RMC", fields) for a valid sentence, otherwise None."""
    line = line.strip()
    if not checksum_ok(line):
        return None
    parts = line[1:].split("*")[0].split(",")
    kind = parts[0][2:]  # drop the talker id (GP, GN, GL...)
    try:
        if kind == "GGA" and parts[6] not in ("", "0"):
            return "GGA", {
                "time_s": _time_s(parts[1]),
                "lat": _degrees(parts[2], parts[3]),
                "lon": _degrees(parts[4], parts[5]),
                "quality": int(parts[6]),
                "satellites": int(parts[7] or 0),
                "hdop": float(parts[8] or 0),
            }
        if kind == "RMC" and parts[2] == "A":
            return "RMC", {
                "time_s": _time_s(parts[1]),
                "lat": _degrees(parts[3], parts[4]),
                "lon": _degrees(parts[5], parts[6]),
                "speed_mps": float(parts[7] or 0) * KNOTS_TO_MPS,
                "course_deg": float(parts[8]) if parts[8] else None,
            }
    except (IndexError, ValueError):
        return None
    return None


def read_fixes(lines: Iterable[str]) -> list[Fix]:
    """Merge GGA and RMC sentences with the same timestamp into one Fix."""
    fixes: dict[float, Fix] = {}
    for line in lines:
        parsed = parse_sentence(line)
        if parsed is None:
            continue
        kind, data = parsed
        fix = fixes.get(data["time_s"])
        if fix is None:
            fix = fixes[data["time_s"]] = Fix(**data)
        elif kind == "GGA":
            fix.lat, fix.lon, fix.quality = data["lat"], data["lon"], data["quality"]
            fix.satellites, fix.hdop = data["satellites"], data["hdop"]
        else:
            fix.speed_mps, fix.course_deg = data["speed_mps"], data["course_deg"]
    return sorted(fixes.values(), key=lambda f: f.time_s)


def read_nmea_file(path: str | Path) -> list[Fix]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return read_fixes(text.splitlines())


def serial_lines(url: str, baudrate: int = 9600, max_lines: int = 1000) -> Iterator[str]:
    """Read NMEA lines from a serial GNSS receiver.

    `url` is anything pyserial understands: "COM5", "/dev/ttyUSB0",
    or "loop://" in tests.
    """
    with serial.serial_for_url(url, baudrate=baudrate, timeout=1) as port:
        for _ in range(max_lines):
            raw = port.readline()
            if not raw:
                return
            yield raw.decode("ascii", errors="replace")
