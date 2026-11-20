from pathlib import Path

import pytest

from fieldbench.bench import load_dbc, simulate
from fieldbench.ecus import RELEASES
from fieldbench.spec import load_spec

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="session")
def spec():
    return load_spec()


@pytest.fixture(scope="session")
def db():
    return load_dbc()


@pytest.fixture(scope="session")
def scenario(spec):
    return spec.scenarios["field_pass"]


@pytest.fixture(scope="session")
def nominal_messages(scenario, db):
    """One nominal field pass on release 1.4.0, shared by many tests."""
    return simulate(scenario, RELEASES["1.4.0"], [], db)


@pytest.fixture(scope="session")
def samples():
    return SAMPLES
