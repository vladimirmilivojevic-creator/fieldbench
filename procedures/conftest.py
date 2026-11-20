"""pytest plumbing for the system test campaign.

    pytest procedures --release 1.3.0 --results results/

Each procedure in spec/system_spec.yaml becomes one test case. At the end of
the session the results go into the Excel/HTML report and the issue tracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fieldbench.bench import load_dbc
from fieldbench.campaign import finish_campaign, now_utc
from fieldbench.ecus import RELEASES
from fieldbench.spec import DEFAULT_SPEC, load_spec


def pytest_addoption(parser):
    group = parser.getgroup("fieldbench")
    group.addoption("--release", default="1.4.0", choices=sorted(RELEASES), help="software release under test")
    group.addoption("--spec", default=str(DEFAULT_SPEC), help="YAML system specification")
    group.addoption("--results", default="results", help="folder for logs, plots, report and issues")
    group.addoption("--no-plots", action="store_true", help="skip signal plots (faster)")


def pytest_configure(config):
    config.fieldbench_results = []
    config.fieldbench_started = now_utc()


def pytest_generate_tests(metafunc):
    if "procedure" in metafunc.fixturenames:
        spec = load_spec(metafunc.config.getoption("--spec"))
        metafunc.parametrize("procedure", spec.procedures, ids=[p.id for p in spec.procedures])


@pytest.fixture(scope="session")
def spec(pytestconfig):
    return load_spec(pytestconfig.getoption("--spec"))


@pytest.fixture(scope="session")
def db():
    return load_dbc()


@pytest.fixture(scope="session")
def bench_options(pytestconfig):
    return {
        "release": pytestconfig.getoption("--release"),
        "out_dir": Path(pytestconfig.getoption("--results")),
        "plots": not pytestconfig.getoption("--no-plots"),
    }


@pytest.fixture
def record(pytestconfig):
    return pytestconfig.fieldbench_results.append


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    results = getattr(config, "fieldbench_results", [])
    if not results:
        return
    spec = load_spec(config.getoption("--spec"))
    out_dir = Path(config.getoption("--results"))
    summary = finish_campaign(spec, config.getoption("--release"), config.fieldbench_started, results, out_dir)
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_line("")
        reporter.write_sep("-", f"FieldBench: {summary.passed} passed, {summary.failed} failed")
        for issue in summary.issues:
            reporter.write_line(f"  {issue.id} [{issue.status}] {issue.title}")
        reporter.write_line(f"  report: {summary.files['html']}")
