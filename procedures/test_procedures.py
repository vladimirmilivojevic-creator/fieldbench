"""System test procedures, generated from spec/system_spec.yaml."""

import pytest

from fieldbench.campaign import run_procedure


def test_procedure(procedure, spec, db, bench_options, record):
    result = run_procedure(spec, procedure, db=db, **bench_options)
    record(result)
    if not result.passed:
        failed = "\n".join(f"  {c.name}: expected {c.expected}, measured {c.measured}" for c in result.failed_checks())
        pytest.fail(f"{procedure.id} {procedure.title}\n{failed}", pytrace=False)
