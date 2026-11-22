"""Structural invariants for the two contract workflows (plan 0.6-contracts-pr3-review-fixes).

The authoritative check for a workflow is its real hosted run, which this checkout
cannot perform. This module is the strongest local evidence available: a real YAML
parse plus an assertion for every rule the plan states, so a later edit cannot
silently drop the least-privilege posture, un-pin an action, or point the job at a
command nobody documented.

The firmware twin, ``tools/firmware/tests/test_workflows.py``, is the model; the one
deliberate difference is that these two jobs publish nothing at all, so they need no
credential beyond reading the repository and carry no `publish` job. Neither filters
paths, for the reason the repo already documents for the firmware workflows (CI-01):
a required check that a commit can leave permanently "Expected" blocks the merge it
exists to certify, and this suite is offline and over in seconds.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = {
    "contracts-pr": REPO_ROOT / ".github/workflows/contracts-pr.yml",
    "contracts-main": REPO_ROOT / ".github/workflows/contracts-main.yml",
}
CHECK = "contracts-validation"

# Resolved with the GitHub API on 2026-11-21 (gh api repos/OWNER/REPO/commits/SHA);
# both are the same pins the firmware workflows already carry.
PINNED_ACTIONS = {
    "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8": "v5.0.0",
    "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78": "v7.6.0",
}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

#: The two commands documented in tools/README.md and contracts/README.md, in the
#: whitespace-normalised form of a shell line. The job runs them with no extra flag,
#: so a green check means exactly what a green local run means.
DOCUMENTED_COMMANDS = (
    "uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock "
    "python tools/validate_contracts.py",
    "uv run --python 3.12 --with-requirements tools/contracts/requirements-dev.lock "
    "pytest tools/contracts/tests",
)

_RAW: dict[str, str] = {}


@pytest.fixture(autouse=True, scope="module")
def _load_raw() -> None:
    for name, path in WORKFLOWS.items():
        _RAW[name] = path.read_text(encoding="utf-8")


def load(name: str) -> dict[str, Any]:
    path = WORKFLOWS[name]
    assert path.is_file(), f"{path} must exist"
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# PyYAML implements YAML 1.1, where the bare `on:` key parses as True.
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow.get("on") or workflow.get(True)


def job(name: str) -> dict[str, Any]:
    return load(name)["jobs"][CHECK]


def steps(workflow_job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(workflow_job.get("steps") or [])


def run_commands(name: str) -> list[str]:
    """Each ``run:`` block as one shell line, continuations and indentation removed.

    The documented commands are wrapped over two lines in the YAML for legibility; the
    shell sees one line. Comparing the joined form is what "verbatim" can mean here
    without making the test sensitive to indentation.
    """
    commands: list[str] = []
    for step in steps(job(name)):
        script = step.get("run")
        if script is None:
            continue
        commands.append(re.sub(r"\s+", " ", str(script).replace("\\\n", " ")).strip())
    return commands


# ---------------------------------------------------------------------------
# Shape and least privilege
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_is_valid_yaml_with_one_read_only_job(name: str) -> None:
    workflow = load(name)
    assert isinstance(workflow["jobs"], dict) and set(workflow["jobs"]) == {CHECK}
    # Top-level least privilege, and no job or step may raise it: this job publishes
    # nothing, so it needs no credential at all beyond reading the repository. The
    # assertion is on the parsed document, because the file's own prose comments say
    # what the job does not do.
    assert workflow["permissions"] == {"contents": "read"}
    for key, value in _walk_permissions(workflow):
        assert value == {"contents": "read"}, f"{name} grants {value!r} at {key}"


def _walk_permissions(node: Any, path: str = "top"):
    """Every ``permissions:`` value in the document, with where it was found."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "permissions":
                yield f"{path}.{key}", value
            else:
                yield from _walk_permissions(value, f"{path}.{key}")
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from _walk_permissions(value, f"{path}[{position}]")


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_only_the_two_reviewed_events_and_no_privileged_one(name: str) -> None:
    on = triggers(load(name))
    assert set(on) <= {"pull_request", "push"}, f"{name} has an unexpected trigger {set(on)}"
    for forbidden in ("pull_request_target", "workflow_run", "workflow_dispatch"):
        assert forbidden not in on, f"{name} must not trigger on {forbidden}"


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_every_third_party_action_is_pinned_to_a_resolved_sha(name: str) -> None:
    workflow = load(name)
    text = _RAW[name]
    for job_name, workflow_job in workflow["jobs"].items():
        for step in steps(workflow_job):
            ref = step.get("uses")
            if not ref:
                continue
            if not ref.startswith(("actions/", "astral-sh/")):
                pytest.fail(f"{name}:{job_name} uses a local/unreviewed action {ref!r}")
            assert "@" in ref and FULL_SHA.match(ref.split("@", 1)[1]), (
                f"{name}:{job_name} {ref!r} is not pinned to a full commit SHA"
            )
            assert ref in PINNED_ACTIONS, f"unreviewed action pin {ref!r}"
            assert ref.split("@", 1)[1] in text and PINNED_ACTIONS[ref] in text, (
                f"{name}:{job_name} must record the resolved commit for {ref}"
            )


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_checkouts_never_persist_credentials(name: str) -> None:
    for step in steps(job(name)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, (
                f"{name} checkout must not persist credentials"
            )


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_stable_check_name_carries_no_variable(name: str) -> None:
    """Branch protection names this check, so it may not vary per commit."""
    assert load(name)["jobs"][CHECK]["name"] == CHECK
    assert "${{" not in str(load(name)["jobs"][CHECK]["name"])


# ---------------------------------------------------------------------------
# The commands that are supposed to be the documented ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_the_job_runs_the_documented_commands_verbatim(name: str) -> None:
    """No extra flag, no reworded invocation: CI green == local green."""
    assert run_commands(name) == list(DOCUMENTED_COMMANDS), name


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_both_families_of_the_suite_are_run(name: str) -> None:
    """The validator alone and pytest alone are not the documented check."""
    script = " ; ".join(run_commands(name))
    assert "python tools/validate_contracts.py" in script
    assert "pytest tools/contracts/tests" in script
    assert " --fix" not in script and "--update" not in script and "pip install" not in script
    assert not re.search(r"\bgit\s+(push|checkout|reset|merge|rebase)\b", script)


def test_the_pr_builds_the_immutable_head_commit() -> None:
    """The built source and the reviewed source are the same commit (CI-02)."""
    checkout = steps(job("contracts-pr"))[0]
    assert str(checkout["uses"]).startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    # The main twin checks out the pushed commit, which is the event SHA by definition.
    assert "ref" not in steps(job("contracts-main"))[0].get("with", {})


def test_neither_workflow_filters_paths() -> None:
    """A required check may not be left permanently "Expected" by a path filter.

    Both twins run the same seconds-long, offline suite, so the cheap failure mode is
    running it everywhere; the expensive one is a branch-protection rule that waits on
    a check no commit can trigger. This is the repo's own documented CI-01 reasoning
    (``firmware-pr.yml``, ``firmware-main.yml``) applied here.
    """
    for name in sorted(WORKFLOWS):
        on = triggers(load(name))
        for event in ("pull_request", "push"):
            if event in on:
                assert "paths" not in (on[event] or {}), f"{name}:{event} must not filter paths"
                assert "paths-ignore" not in (on[event] or {}), f"{name}:{event} must not filter paths"


def test_the_pr_triggers_on_the_default_set_of_pr_events() -> None:
    """No `types:` narrowing either, which would leave the check pending the same way."""
    pull_request = triggers(load("contracts-pr"))["pull_request"] or {}
    assert "types" not in pull_request, pull_request
    assert triggers(load("contracts-main"))["push"]["branches"] == ["main"]
