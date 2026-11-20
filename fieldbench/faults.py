"""Fault injection node, sitting between the ECUs and the bus.

Fault types (as written in the YAML spec):
  drop          - frames of one message are lost
  gnss_dropout  - the GNSS receiver goes silent (antenna blocked, receiver reset)
  bus_off       - one ECU leaves the bus (all its frames are missing)
  bus_errors    - frames are destroyed by error frames and retransmitted,
                  like on a bus with a bad termination or a loose connector
"""

from __future__ import annotations

from dataclasses import dataclass

import can

KNOWN_TYPES = {"drop", "gnss_dropout", "bus_off", "bus_errors"}
RETRANSMIT_DELAY_S = 0.0006  # one error frame + interframe space at 250 kbit/s


@dataclass(frozen=True)
class Fault:
    type: str
    at_s: float
    duration_s: float
    message: str | None = None
    ecu: str | None = None
    rate_per_s: float = 0

    def active(self, t_ms: int) -> bool:
        return self.at_s * 1000 <= t_ms < (self.at_s + self.duration_s) * 1000

    def drops(self, sender: str, name: str) -> bool:
        return (
            (self.type == "drop" and name == self.message)
            or (self.type == "gnss_dropout" and sender == "GNSS")
            or (self.type == "bus_off" and sender == self.ecu)
        )


class FaultInjector:
    def __init__(self, faults: list[dict] | None = None):
        self.faults = [Fault(**f) for f in faults or []]
        unknown = {f.type for f in self.faults} - KNOWN_TYPES
        if unknown:
            raise ValueError(f"unknown fault type(s): {sorted(unknown)}")
        self._next_error_ms: dict[int, float] = {}
        self.error_frames = 0

    def apply(self, sender: str, name: str, msg: can.Message, t_ms: int) -> list[can.Message]:
        """Return the frames that really reach the bus for one transmit request."""
        for i, fault in enumerate(self.faults):
            if not fault.active(t_ms):
                continue
            if fault.drops(sender, name):
                return []
            if fault.type == "bus_errors" and self._error_due(i, fault, t_ms):
                self.error_frames += 1
                error = can.Message(timestamp=msg.timestamp, is_error_frame=True)
                retry = can.Message(
                    arbitration_id=msg.arbitration_id,
                    is_extended_id=True,
                    data=msg.data,
                    timestamp=msg.timestamp + RETRANSMIT_DELAY_S,
                )
                return [error, retry]
        return [msg]

    def _error_due(self, index: int, fault: Fault, t_ms: int) -> bool:
        """Spread error frames evenly: one every 1000 / rate_per_s ms."""
        nxt = self._next_error_ms.get(index, fault.at_s * 1000)
        if t_ms < nxt:
            return False
        self._next_error_ms[index] = nxt + 1000 / fault.rate_per_s
        return True

    def windows(self) -> list[tuple[float, float, str]]:
        """Fault time windows for shading in plots."""
        return [(f.at_s, f.at_s + f.duration_s, f.type) for f in self.faults]
