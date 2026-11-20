"""Plant model: the "real world" the simulated ECUs measure.

On a HIL bench this would be the vehicle model running on the simulator.
Here it is a pure function of time, so every run is reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .guidance import EARTH_RADIUS_M
from .spec import Scenario

IDLE_RPM = 850
RAMP_START_S = 0.5
RAMP_S = 3.0
HITCH_TRANSPORT_PCT = 80.0
HITCH_WORK_PCT = 20.0
# The hitch position sensor reads slightly above 100 % at the mechanical end
# stop. The tractor ECU must clamp this before it goes on the bus.
HITCH_END_STOP_PCT = 102.0


@dataclass(frozen=True)
class VehicleState:
    engine_rpm: float
    speed_mps: float
    distance_m: float
    hitch_pct: float
    lat: float
    lon: float
    course_deg: float
    lateral_m: float


class Plant:
    def __init__(self, scenario: Scenario):
        self.s = scenario
        self.v_max = scenario.speed_kmh / 3.6

    def speed(self, t: float) -> float:
        if t <= RAMP_START_S:
            return 0.0
        return self.v_max * min(1.0, (t - RAMP_START_S) / RAMP_S)

    def distance(self, t: float) -> float:
        """Integral of speed(t), in closed form."""
        if t <= RAMP_START_S:
            return 0.0
        ramp_t = min(t - RAMP_START_S, RAMP_S)
        d = self.v_max * ramp_t**2 / (2 * RAMP_S)
        if t > RAMP_START_S + RAMP_S:
            d += self.v_max * (t - RAMP_START_S - RAMP_S)
        return d

    def engine_rpm(self, t: float) -> float:
        ramp = min(1.0, t / 2.0)
        ripple = 8 * math.sin(2 * math.pi * t * 1.7)
        return IDLE_RPM + (self.s.engine_rpm - IDLE_RPM) * ramp + ripple

    def hitch(self, t: float) -> float:
        if t < self.s.hitch_lower_s:
            return HITCH_TRANSPORT_PCT
        if t < self.s.hitch_raise_s:
            k = min(1.0, (t - self.s.hitch_lower_s) / 1.0)
            return HITCH_TRANSPORT_PCT + (HITCH_WORK_PCT - HITCH_TRANSPORT_PCT) * k
        k = min(1.0, (t - self.s.hitch_raise_s) / 1.0)
        return HITCH_WORK_PCT + (HITCH_END_STOP_PCT - HITCH_WORK_PCT) * k

    def state(self, t: float) -> VehicleState:
        along = self.distance(t)
        # A small steering oscillation around the line, like a real auto-steer
        # system holding a few centimetres.
        lateral = 0.03 * math.sin(2 * math.pi * t / 8)
        h = math.radians(self.s.heading_deg)
        north = along * math.cos(h) - lateral * math.sin(h)
        east = along * math.sin(h) + lateral * math.cos(h)
        lat = self.s.origin_lat + math.degrees(north / EARTH_RADIUS_M)
        lon = self.s.origin_lon + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(self.s.origin_lat))))
        return VehicleState(
            engine_rpm=self.engine_rpm(t),
            speed_mps=self.speed(t),
            distance_m=along,
            hitch_pct=self.hitch(t),
            lat=lat,
            lon=lon,
            course_deg=self.s.heading_deg,
            lateral_m=lateral,
        )
