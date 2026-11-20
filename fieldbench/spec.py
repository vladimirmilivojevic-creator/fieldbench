"""Load the YAML system specification into small dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_SPEC = Path(__file__).resolve().parent.parent / "spec" / "system_spec.yaml"


@dataclass(frozen=True)
class MessageSpec:
    name: str
    cycle_ms: float
    tolerance_pct: float
    timeout_ms: float


@dataclass(frozen=True)
class SignalSpec:
    name: str
    min: float
    max: float
    unit: str = ""


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    safety: bool = False


@dataclass(frozen=True)
class Scenario:
    name: str
    duration_s: float
    engine_rpm: float
    speed_kmh: float
    origin_lat: float
    origin_lon: float
    heading_deg: float
    operator_engage_s: float
    hitch_lower_s: float
    hitch_raise_s: float


@dataclass(frozen=True)
class Procedure:
    id: str
    title: str
    requirement: str
    scenario: str
    checks: list[dict]
    faults: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Spec:
    system: str
    bitrate: int
    messages: dict[str, MessageSpec]
    signals: dict[str, SignalSpec]
    requirements: dict[str, Requirement]
    scenarios: dict[str, Scenario]
    guidance: dict
    procedures: list[Procedure]

    def procedure(self, procedure_id: str) -> Procedure:
        for procedure in self.procedures:
            if procedure.id == procedure_id:
                return procedure
        raise KeyError(f"unknown procedure {procedure_id}")


def load_spec(path: str | Path = DEFAULT_SPEC) -> Spec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    spec = Spec(
        system=raw["system"],
        bitrate=raw["bus"]["bitrate"],
        messages={name: MessageSpec(name, **cfg) for name, cfg in raw["messages"].items()},
        signals={name: SignalSpec(name, **cfg) for name, cfg in raw["signals"].items()},
        requirements={rid: Requirement(rid, **cfg) for rid, cfg in raw["requirements"].items()},
        scenarios={name: _scenario(name, cfg) for name, cfg in raw["scenarios"].items()},
        guidance=raw["guidance"],
        procedures=[Procedure(**p) for p in raw["procedures"]],
    )
    _validate(spec)
    return spec


def _scenario(name: str, cfg: dict) -> Scenario:
    origin = cfg.pop("origin")
    return Scenario(name=name, origin_lat=origin["lat"], origin_lon=origin["lon"], **cfg)


def _validate(spec: Spec) -> None:
    """Fail early on typos in the spec instead of producing a confusing test result."""
    ids = [p.id for p in spec.procedures]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate procedure id in spec")
    for p in spec.procedures:
        if p.requirement not in spec.requirements:
            raise ValueError(f"{p.id}: unknown requirement {p.requirement}")
        if p.scenario not in spec.scenarios:
            raise ValueError(f"{p.id}: unknown scenario {p.scenario}")
