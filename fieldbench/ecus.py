"""Simulated ECUs: engine, tractor ECU, GNSS receiver and guidance controller.

Each ECU sends its messages on a fixed cycle and may react to frames it
receives. Software release 1.3.0 contains three seeded defects so the bench
has something real to find; release 1.4.0 fixes them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import can
import cantools

from .guidance import AbLine
from .plant import VehicleState
from .spec import Scenario


@dataclass(frozen=True)
class Release:
    version: str
    clamps_hitch_position: bool  # 1.3.0: sensor overshoot 102 % goes on the bus as raw 0xFF
    clears_engage_request: bool  # 1.3.0: request stays latched -> steering re-engages by itself
    cog_sog_period_ms: int  # 1.3.0: 280 ms instead of 250 ms
    notes: str


RELEASES = {
    "1.3.0": Release("1.3.0", False, False, 280, "Release candidate with three seeded defects"),
    "1.4.0": Release("1.4.0", True, True, 250, "Fixes FB-001..FB-003"),
}

# Exit reason codes in GUIDANCE_STATUS (see VAL_ table in the DBC).
EXIT_NONE, EXIT_OPERATOR, EXIT_GNSS_LOST, EXIT_SPEED_LOST, EXIT_SPEED_RANGE = range(5)
SIGNAL_TIMEOUT_MS = 300
MIN_STEER_SPEED_MPS = 0.5
MAX_STEER_SPEED_MPS = 15.0
SPN_LATITUDE, FMI_ABNORMAL_UPDATE_RATE = 584, 9


class Ecu:
    name = "ECU"
    periods_ms: dict[str, int] = {}
    listens: frozenset[str] = frozenset()  # messages this ECU reads from the bus

    def __init__(self, db: cantools.database.Database, release: Release, scenario: Scenario, rng: random.Random):
        self.db = db
        self.release = release
        self.scenario = scenario
        self.rng = rng
        self._next_ms = dict.fromkeys(self.periods_ms, 0)

    def due(self, t_ms: int) -> list[str]:
        names = [name for name, nxt in self._next_ms.items() if t_ms >= nxt]
        for name in names:
            self._next_ms[name] += self.periods_ms[name]
        return names

    def frame(self, name: str, values: dict, t_ms: int) -> can.Message:
        msg = self.db.get_message_by_name(name)
        # strict=False: like real firmware, the ECU does not range-check
        # what it sends. Catching bad values is the bench's job.
        data = self.db.encode_message(name, values, strict=False)
        jitter_ms = self.rng.uniform(-0.8, 0.8)  # scheduler jitter of a real ECU
        return can.Message(
            arbitration_id=msg.frame_id,
            is_extended_id=True,
            data=data,
            timestamp=max(0.0, (t_ms + jitter_ms) / 1000),
        )

    def values(self, name: str, state: VehicleState, t_ms: int) -> dict:
        raise NotImplementedError

    def send(self, t_ms: int, state: VehicleState) -> list[can.Message]:
        return [self.frame(name, self.values(name, state, t_ms), t_ms) for name in self.due(t_ms)]

    def receive(self, name: str, signals: dict, t_ms: int) -> None:
        """Most ECUs only transmit."""

    def update(self, t_ms: int) -> None:
        """Internal state machine, called every bench step."""


class EngineEcu(Ecu):
    name = "ENGINE"
    periods_ms = {"EEC1": 20}

    def values(self, name, state, t_ms):
        return {"EngineSpeed": state.engine_rpm, "ActualEnginePercentTorque": 35}


class TractorEcu(Ecu):
    name = "TECU"
    periods_ms = {"WBSD": 100, "RHS": 100}

    def values(self, name, state, t_ms):
        if name == "WBSD":
            return {
                "WheelBasedSpeed": state.speed_mps,
                "WheelBasedDistance": state.distance_m,
                "MachineDirection": 1,
            }
        position = state.hitch_pct
        if self.release.clamps_hitch_position:
            position = min(position, 100.0)
        return {"RearHitchPosition": position, "RearHitchInWork": int(position < 50)}


class GnssReceiver(Ecu):
    name = "GNSS"

    def __init__(self, db, release, scenario, rng):
        self.periods_ms = {"GNSS_POSITION": 100, "GNSS_COG_SOG": release.cog_sog_period_ms}
        super().__init__(db, release, scenario, rng)
        self.sid = 0

    def values(self, name, state, t_ms):
        if name == "GNSS_POSITION":
            return {"Latitude": state.lat, "Longitude": state.lon}
        self.sid = (self.sid + 1) % 253
        return {
            "SID": self.sid,
            "CogReference": 0,
            "CourseOverGround": math.radians(state.course_deg),
            "SpeedOverGround": state.speed_mps,
        }


class GuidanceController(Ecu):
    """Auto-steering: engages on operator request, disengages on bad inputs."""

    name = "GUIDANCE"
    periods_ms = {"GUIDANCE_STATUS": 100, "DM1": 1000}
    listens = frozenset({"GNSS_POSITION", "WBSD"})

    def __init__(self, db, release, scenario, rng):
        super().__init__(db, release, scenario, rng)
        self.line = AbLine.from_heading(scenario.origin_lat, scenario.origin_lon, scenario.heading_deg)
        self.engage_at_ms = int(scenario.operator_engage_s * 1000)
        self.last_gnss_ms = self.last_speed_ms = -math.inf
        self.gnss_seen = False
        self.speed = 0.0
        self.xte = 0.0
        self.engaged = False
        self.ready = False
        self.engage_requested = False
        self.exit_reason = EXIT_NONE
        self.dtc_active = False
        self.dtc_changed = False

    def receive(self, name, signals, t_ms):
        if name == "GNSS_POSITION":
            self.last_gnss_ms, self.gnss_seen = t_ms, True
            self.xte = self.line.cross_track_error(signals["Latitude"], signals["Longitude"])
        elif name == "WBSD":
            self.last_speed_ms = t_ms
            self.speed = signals["WheelBasedSpeed"]

    def update(self, t_ms):
        if t_ms == self.engage_at_ms:
            self.engage_requested = True  # operator presses "engage" on the terminal

        gnss_ok = t_ms - self.last_gnss_ms <= SIGNAL_TIMEOUT_MS
        speed_ok = t_ms - self.last_speed_ms <= SIGNAL_TIMEOUT_MS
        ready = gnss_ok and speed_ok and MIN_STEER_SPEED_MPS <= self.speed <= MAX_STEER_SPEED_MPS

        if self.engaged and not ready:
            self.engaged = False
            if not gnss_ok:
                self.exit_reason = EXIT_GNSS_LOST
            elif not speed_ok:
                self.exit_reason = EXIT_SPEED_LOST
            else:
                self.exit_reason = EXIT_SPEED_RANGE
        elif not self.engaged and self.engage_requested and ready:
            self.engaged = True
            self.exit_reason = EXIT_NONE
            if self.release.clears_engage_request:
                self.engage_requested = False

        dtc = self.gnss_seen and not gnss_ok
        if dtc != self.dtc_active:
            self.dtc_active, self.dtc_changed = dtc, True
        self.ready = ready

    def send(self, t_ms, state):
        names = self.due(t_ms)
        # J1939-73: DM1 is sent every second and also when the DTC state changes.
        if self.dtc_changed and "DM1" not in names:
            names.append("DM1")
        self.dtc_changed = False
        return [self.frame(name, self.values(name, state, t_ms), t_ms) for name in names]

    def values(self, name, state, t_ms):
        if name == "GUIDANCE_STATUS":
            return {
                "SteeringEngaged": int(self.engaged),
                "SteeringReadiness": int(self.ready),
                "ExitReason": self.exit_reason,
                "CrossTrackError": max(-32.0, min(32.0, self.xte)),
            }
        spn = SPN_LATITUDE if self.dtc_active else 0
        return {
            "ProtectLamp": 0,
            "AmberWarningLamp": int(self.dtc_active),
            "RedStopLamp": 0,
            "MalfunctionLamp": 0,
            "SpnLow": spn & 0xFFFF,
            "SpnHigh": spn >> 16,
            "Fmi": FMI_ABNORMAL_UPDATE_RATE if self.dtc_active else 0,
            "OccurrenceCount": int(self.dtc_active),
        }


ECU_TYPES = (EngineEcu, TractorEcu, GnssReceiver, GuidanceController)


def build_ecus(db, release: Release, scenario: Scenario, seed: int = 1) -> list[Ecu]:
    rng = random.Random(seed)
    return [cls(db, release, scenario, rng) for cls in ECU_TYPES]
