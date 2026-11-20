"""Root-cause tools for CAN logs: decode, find dropouts, plot signals.

Works the same on a bench recording and on a Vector ASC/BLF log from the
field, because both end up as a list of python-can Messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import can
import cantools
import pandas as pd


@dataclass
class Capture:
    """Decoded log: one DataFrame per message (time + signal columns)."""

    frames: pd.DataFrame  # t, name, arbitration_id, error
    tables: dict[str, pd.DataFrame]

    def signal(self, name: str) -> pd.Series:
        for table in self.tables.values():
            if name in table.columns:
                return table.set_index("t")[name]
        raise KeyError(f"signal {name} not in capture")

    def times(self, message: str) -> pd.Series:
        table = self.tables.get(message)
        return table["t"] if table is not None else pd.Series(dtype=float)

    @property
    def error_frames(self) -> int:
        return int(self.frames["error"].sum()) if not self.frames.empty else 0


def decode(messages: list[can.Message], db: cantools.database.Database) -> Capture:
    frame_rows, rows_by_message = [], {}
    for msg in messages:
        if msg.is_error_frame:
            frame_rows.append({"t": msg.timestamp, "name": "ERROR_FRAME", "arbitration_id": 0, "error": True})
            continue
        try:
            message = db.get_message_by_frame_id(msg.arbitration_id)
        except KeyError:
            name = f"0x{msg.arbitration_id:X}"
            frame_rows.append({"t": msg.timestamp, "name": name, "arbitration_id": msg.arbitration_id, "error": False})
            continue
        frame_rows.append(
            {"t": msg.timestamp, "name": message.name, "arbitration_id": msg.arbitration_id, "error": False}
        )
        values = message.decode(msg.data, decode_choices=False)
        rows_by_message.setdefault(message.name, []).append({"t": msg.timestamp, **values})
    frames = pd.DataFrame(frame_rows, columns=["t", "name", "arbitration_id", "error"])
    tables = {name: pd.DataFrame(rows) for name, rows in rows_by_message.items()}
    return Capture(frames, tables)


def write_logs(messages: list[can.Message], stem: str | Path) -> tuple[Path, Path]:
    """Write the same recording as Vector BLF (binary) and ASC (text)."""
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    # not with_suffix(): release names like "1.4.0" contain dots
    paths = (Path(f"{stem}.blf"), Path(f"{stem}.asc"))
    for path in paths:
        with can.Logger(str(path)) as logger:
            for msg in messages:
                logger.on_message_received(msg)
    return paths


def read_log(path: str | Path) -> list[can.Message]:
    """Read a Vector .asc or .blf (or any format python-can supports)."""
    with can.LogReader(str(path)) as reader:
        return list(reader)


@dataclass(frozen=True)
class Dropout:
    message: str
    start_s: float
    end_s: float

    @property
    def gap_ms(self) -> float:
        return round((self.end_s - self.start_s) * 1000, 1)


def find_dropouts(capture: Capture, cycles_ms: dict[str, float], factor: float = 3.0) -> list[Dropout]:
    """A dropout is a gap longer than `factor` x the nominal cycle time."""
    dropouts = []
    for name, cycle in cycles_ms.items():
        t = capture.times(name).reset_index(drop=True)
        gaps = t.diff()
        for i in gaps[gaps * 1000 > cycle * factor].index:
            dropouts.append(Dropout(name, float(t[i - 1]), float(t[i])))
    return sorted(dropouts, key=lambda d: d.start_s)


def dbc_cycle_times(db: cantools.database.Database) -> dict[str, float]:
    return {m.name: m.cycle_time for m in db.messages if m.cycle_time}


def message_stats(capture: Capture, cycles_ms: dict[str, float]) -> pd.DataFrame:
    rows = []
    for name, cycle in cycles_ms.items():
        diffs = capture.times(name).diff().dropna() * 1000
        rows.append(
            {
                "message": name,
                "frames": int(len(capture.times(name))),
                "nominal_ms": cycle,
                "mean_ms": round(float(diffs.mean()), 1) if len(diffs) else None,
                "max_gap_ms": round(float(diffs.max()), 1) if len(diffs) else None,
            }
        )
    return pd.DataFrame(rows)


def asc_excerpt(
    messages: list[can.Message], db: cantools.database.Database, t_from: float, t_to: float, limit: int = 40
) -> str:
    """ASC-style lines around an event, with the decoded values as comments."""
    lines = []
    for msg in messages:
        if not t_from <= msg.timestamp <= t_to:
            continue
        if msg.is_error_frame:
            lines.append(f"{msg.timestamp:11.6f} 1  ErrorFrame")
            continue
        data = " ".join(f"{b:02X}" for b in msg.data)
        line = f"{msg.timestamp:11.6f} 1  {msg.arbitration_id:X}x  Rx   d {msg.dlc} {data}"
        try:
            message = db.get_message_by_frame_id(msg.arbitration_id)
            values = message.decode(msg.data, decode_choices=False)
            decoded = " ".join(f"{k}={_fmt(v)}" for k, v in values.items())
            line += f"  // {message.name} {decoded}"
        except KeyError:
            pass
        lines.append(line)
        if len(lines) >= limit:
            lines.append("...")
            break
    return "\n".join(lines)


def _fmt(value) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def plot_signals(
    capture: Capture,
    signals: list[str],
    path: str | Path,
    spans: list[tuple[float, float, str]] | None = None,
    dropouts: list[Dropout] | None = None,
    title: str = "",
) -> Path:
    """One subplot per signal; fault windows shaded orange, dropouts red."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    signals = [s for s in signals if _has(capture, s)]
    fig, axes = plt.subplots(len(signals), 1, figsize=(10, 1.6 * len(signals) + 0.8), sharex=True, squeeze=False)
    for ax, name in zip(axes[:, 0], signals, strict=True):
        series = capture.signal(name)
        ax.step(series.index, series.values, where="post", lw=1.2, color="#1b5e20")
        ax.set_ylabel(name, rotation=0, ha="right", va="center", fontsize=8)
        ax.ticklabel_format(axis="y", useOffset=False, style="plain")
        ax.grid(alpha=0.3)
        for start, end, label in spans or []:
            ax.axvspan(start, end, color="#ff9800", alpha=0.18, label=label)
        for d in dropouts or []:
            ax.axvspan(d.start_s, d.end_s, color="#e53935", alpha=0.25)
    axes[-1, 0].set_xlabel("time [s]")
    if title:
        fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return Path(path)


def _has(capture: Capture, signal: str) -> bool:
    try:
        capture.signal(signal)
        return True
    except KeyError:
        return False
