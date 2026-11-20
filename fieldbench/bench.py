"""The test bench: ECUs + fault injector + recorder on one virtual CAN bus.

Time is simulated (fixed 5 ms steps) instead of wall-clock time, so a
14-second field pass runs in a fraction of a second and gives the same
result on every run and every machine. The frames still go through a real
python-can bus: swap `interface="virtual"` for "vector", "pcan" or
"socketcan" in BenchConfig and the recorder listens to real hardware.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import can
import cantools

from .ecus import Ecu, build_ecus
from .faults import FaultInjector
from .plant import Plant
from .spec import Scenario

DBC_PATH = Path(__file__).resolve().parent / "dbc" / "fieldbench.dbc"
STEP_MS = 5


def load_dbc(path: str | Path = DBC_PATH) -> cantools.database.Database:
    return cantools.database.load_file(str(path))


@dataclass(frozen=True)
class BenchConfig:
    interface: str = "virtual"
    channel: str | None = None  # None = a fresh private virtual channel per run


def _drain(bus: can.BusABC) -> list[can.Message]:
    frames = []
    while (msg := bus.recv(timeout=0)) is not None:
        frames.append(msg)
    return frames


class Bench:
    def __init__(
        self,
        db: cantools.database.Database,
        ecus: list[Ecu],
        plant: Plant,
        injector: FaultInjector,
        config: BenchConfig = BenchConfig(),
    ):
        self.db = db
        self.ecus = ecus
        self.plant = plant
        self.injector = injector
        self.config = config

    def _open(self, channel: str, receive_own: bool = False) -> can.BusABC:
        return can.Bus(
            interface=self.config.interface,
            channel=channel,
            preserve_timestamps=True,
            receive_own_messages=receive_own,
        )

    def run(self, duration_s: float) -> list[can.Message]:
        """Run the bench and return every frame the recorder saw, in time order."""
        channel = self.config.channel or f"fieldbench-{uuid.uuid4().hex[:8]}"
        # All simulated ECUs share one bus interface (like simulated nodes in
        # CANoe); the recorder is a separate interface, like a logger on the bus.
        nodes = self._open(channel, receive_own=True)
        recorder = self._open(channel)
        recorded: list[can.Message] = []
        try:
            for t_ms in range(0, int(duration_s * 1000) + 1, STEP_MS):
                # 1. deliver what arrived since the last step to every ECU
                for msg in _drain(nodes):
                    self._deliver(msg, t_ms)
                recorded.extend(_drain(recorder))

                # 2. every ECU updates its state and transmits what is due
                state = self.plant.state(t_ms / 1000)
                for ecu in self.ecus:
                    ecu.update(t_ms)
                    for msg in ecu.send(t_ms, state):
                        name = self.db.get_message_by_frame_id(msg.arbitration_id).name
                        for out in self.injector.apply(ecu.name, name, msg, t_ms):
                            nodes.send(out)
            recorded.extend(_drain(recorder))
        finally:
            nodes.shutdown()
            recorder.shutdown()
        for msg in recorded:
            msg.channel = 0  # log as CAN 1, not as the virtual channel name
        return sorted(recorded, key=lambda m: m.timestamp)

    def _deliver(self, msg: can.Message, t_ms: int) -> None:
        if msg.is_error_frame:
            return
        try:
            message = self.db.get_message_by_frame_id(msg.arbitration_id)
        except KeyError:
            return  # unknown frame: ignore, like a real ECU
        listeners = [ecu for ecu in self.ecus if message.name in ecu.listens]
        if listeners:
            signals = message.decode(msg.data, decode_choices=False)
            for ecu in listeners:
                ecu.receive(message.name, signals, t_ms)


def simulate(
    scenario: Scenario,
    release,
    faults: list[dict] | None = None,
    db: cantools.database.Database | None = None,
    seed: int = 1,
) -> list[can.Message]:
    db = db or load_dbc()
    bench = Bench(db, build_ecus(db, release, scenario, seed), Plant(scenario), FaultInjector(faults))
    return bench.run(scenario.duration_s)
