"""The code registry (``tools/contracts/errors.py``) is part of the contract.

A code is a public name once a fixture declares it, so: every constant is registered,
every registered constant is spelled exactly like its name, every emitted code is
registered, and every registered code is actually exercised somewhere.
"""

from __future__ import annotations

import json

from tools.contracts import (
    api_validate,
    errors,
    media_validate,
    openapi_check,
    validate,
)
from tools.contracts.errors import CODES, Violation

def test_every_registered_code_is_exercised(report, oversized_codes, mutation_codes) -> None:
    """A code nothing can reach is dead weight in a published contract.

    A code counts as exercised when a committed vector, a synthetic oversized vector or
    one of the broken-copy scenarios in ``conftest.CORPUS_MUTATIONS`` actually produced
    it. There is deliberately no exemption list: a code nobody can make appear has to be
    deleted, not annotated.
    """
    observed = {violation.code for result in report.results for violation in result.violations}
    for codes in mutation_codes.values():
        observed |= codes
    observed |= set(oversized_codes)
    unexercised = set(CODES) - observed
    assert not unexercised, sorted(unexercised)

def test_every_module_constant_is_registered_and_self_named() -> None:
    constants = {
        name: value
        for name, value in vars(errors).items()
        if name.isupper() and isinstance(value, str)
    }
    assert constants, "the registry must define codes"
    for name, value in constants.items():
        assert name == value, f"{name} = {value!r} must be spelled identically"
        assert value in CODES, f"{value} is defined but not registered in CODES"
    for value in CODES:
        assert value in constants.values(), f"{value} is registered but never defined"


def test_every_code_reference_resolves_to_a_registered_name() -> None:
    """``E.NAME`` must be a registered code, so a typo cannot become a silent new code."""
    import re
    from pathlib import Path

    pattern = re.compile(r"\bE\.([A-Z][A-Z0-9_]+)\b")
    modules = (media_validate, api_validate, openapi_check, validate)
    unknown: set[str] = set()
    for module in modules:
        source = Path(module.__file__).read_text(encoding="utf-8")
        for name in pattern.findall(source):
            if name not in CODES:
                unknown.add(f"{module.__name__}:{name}")
    assert not unknown, sorted(unknown)


def test_every_fixture_declared_code_is_registered() -> None:
    from conftest import FIXTURES

    document = json.loads((FIXTURES / "fixtures.json").read_bytes().decode("utf-8"))
    for entry in document["fixtures"]:
        for code in entry["expected_error_codes"]:
            assert code in CODES, (entry["id"], code)


def test_violation_rendering_is_stable() -> None:
    assert Violation("CODE", "where").render() == "CODE: where"
    assert Violation("CODE", "where", "why").render() == "CODE: where: why"
