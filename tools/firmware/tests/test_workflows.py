"""Structural invariants for the two firmware workflows (master plan 0.9.14).

The authoritative check for a workflow is its real hosted run, which this
checkout cannot perform. This module is the strongest local evidence available:
a real YAML parse plus assertions for every rule the plan requires (CI-T01,
CI-T02, CI-T04, CI-T05, CI-T12, CI-T13) so a later edit cannot silently break
one. ``actionlint`` is not installed on this host; when it becomes available it
complements, and does not replace, these assertions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = {
    "firmware-pr": REPO_ROOT / ".github/workflows/firmware-pr.yml",
    "firmware-main": REPO_ROOT / ".github/workflows/firmware-main.yml",
}

# Resolved with the GitHub API on 2026-11-21; each commit's own tag ref matches.
PINNED_ACTIONS = {
    "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8": "v5.0.0",
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02": "v4.6.2",
    "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093": "v4.3.0",
    "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78": "v7.6.0",
    "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830": "v4.3.0",
}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
STABLE_CHECKS = ("firmware-build", "firmware-host-tests", "firmware-package-tests")
_RAW: dict[str, str] = {}


def load(name: str) -> dict[str, Any]:
    path = WORKFLOWS[name]
    assert path.is_file(), f"{path} must exist"
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# PyYAML implements YAML 1.1, where the bare `on:` key parses as True.
def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow.get("on") or workflow.get(True)


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


def uses(job: dict[str, Any]) -> list[str]:
    return [s["uses"] for s in steps(job) if "uses" in s]


# ---------------------------------------------------------------------------
# Parsing and shared shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_is_valid_yaml_with_the_expected_shape(name: str) -> None:
    workflow = load(name)
    assert workflow["name"] == name
    assert isinstance(workflow["jobs"], dict) and workflow["jobs"]
    # Top-level least privilege: read-only contents everywhere by default.
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) >= set(STABLE_CHECKS)


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_no_path_filters_and_no_forbidden_events(name: str) -> None:
    """CI-T01: documentation changes run the same build; no privileged events."""
    on = triggers(load(name))
    assert set(on) <= {"pull_request", "push"}, f"{name} has an unexpected trigger {set(on)}"
    for key in ("pull_request", "push"):
        if key in on:
            assert "paths" not in (on[key] or {}), f"{name}:{key} must not filter paths"
    for forbidden in ("pull_request_target", "workflow_run", "workflow_dispatch"):
        assert forbidden not in on, f"{name} must not trigger on {forbidden}"


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_every_third_party_action_is_pinned_to_a_resolved_sha(name: str) -> None:
    """CI-T12: full commit SHA, and the comment records the resolved commit."""
    workflow = load(name)
    text = _RAW[name]
    for job_name, job in workflow["jobs"].items():
        for step in steps(job):
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


@pytest.fixture(autouse=True, scope="module")
def _load_raw() -> None:
    for name, path in WORKFLOWS.items():
        _RAW[name] = path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_checkouts_never_persist_credentials(name: str) -> None:
    for job_name, job in load(name)["jobs"].items():
        for step in steps(job):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step.get("with", {}).get("persist-credentials") is False, (
                    f"{name}:{job_name} checkout must not persist credentials"
                )


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_stable_check_names_contain_no_variable(name: str) -> None:
    """CI-T04: required-check names are constant across commits and runs."""
    for check in STABLE_CHECKS:
        job = load(name)["jobs"][check]
        assert job["name"] == check
        assert "${{" not in str(job["name"])
        assert "${{" not in check


# ---------------------------------------------------------------------------
# firmware-pr specifics
# ---------------------------------------------------------------------------


def test_pr_builds_the_immutable_head_sha_not_the_merge_ref() -> None:
    """CI-T02."""
    workflow = load("firmware-pr")
    assert triggers(workflow)["pull_request"]["types"] == [
        "opened",
        "reopened",
        "synchronize",
        "ready_for_review",
    ]
    for check in STABLE_CHECKS:
        job = workflow["jobs"][check]
        checkout = steps(job)[0]
        assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
        assert checkout["with"]["persist-credentials"] is False
    build_steps = steps(workflow["jobs"]["firmware-build"])
    identity = next(s for s in build_steps if s.get("id") == "identity")
    # The built source is the immutable head SHA, and the job fails unless the
    # checkout really is that commit; the merge SHA is never built.
    assert identity["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert identity["env"]["PR_NUMBER"] == "${{ github.event.pull_request.number }}"
    build = "\n".join(str(s.get("run", "")) for s in build_steps)
    assert 'checked_out="$(git rev-parse HEAD)"' in build
    assert '"$HEAD_SHA"' in build
    assert "GITHUB_SHA" in build  # recorded as explicitly not built
    package = next(s for s in build_steps if "tools.firmware.package" in str(s.get("run", "")))
    assert package["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"


def test_pr_cancels_superseded_runs_per_pr_number() -> None:
    """CI-T13."""
    concurrency = load("firmware-pr")["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert concurrency["group"] == "firmware-pr-${{ github.event.pull_request.number }}"


def test_pr_artifact_is_head_hash_named_and_retained_14_days() -> None:
    job = load("firmware-pr")["jobs"]["firmware-build"]
    body = "\n".join(str(s.get("run", "")) for s in steps(job))
    assert "vdog-xiao-sense-pr-${PR_NUMBER}-${sha12}" in body
    assert "run${RUN_ID}-a${ATTEMPT}" in body
    upload = next(s for s in steps(job) if "upload-artifact@" in str(s.get("uses")))
    assert upload["with"]["retention-days"] == 14
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["name"] == "${{ steps.identity.outputs.artifact_name }}"
    assert str(upload["with"]["path"]).count("package_zip") == 2  # ZIP + external digest


def test_pr_build_never_runs_pio_test_before_packaging() -> None:
    """CI-T03: `pio test` uses a separate build directory in its own job."""
    job = load("firmware-pr")["jobs"]["firmware-build"]
    assert not any("pio test" in str(s.get("run", "")) for s in steps(job))
    host = load("firmware-pr")["jobs"]["firmware-host-tests"]
    assert any("pio test -d firmware -e native" in str(s.get("run", "")) for s in steps(host))


def test_pr_build_validates_the_package_and_runs_the_packaged_check() -> None:
    job = load("firmware-pr")["jobs"]["firmware-build"]
    body = "\n".join(str(s.get("run", "")) for s in steps(job))
    assert "python -m tools.firmware.package" in body
    assert "install.py\" check" in body or "install.py' check" in body
    assert "--release-kind pr" in body
    assert "--pr-number" in body


@pytest.mark.parametrize("name", ["firmware-pr", "firmware-main"])
def test_no_write_credentials_outside_publish(name: str) -> None:
    """CI-T12: only the main publish job may write."""
    for job_name, job in load(name)["jobs"].items():
        permissions = job.get("permissions")
        if (name, job_name) == ("firmware-main", "publish"):
            assert permissions == {"contents": "write", "actions": "read"}
        else:
            assert permissions is None, f"{name}:{job_name} must inherit read-only"
        body = "\n".join(
            [str(s.get("run", "")) for s in steps(job)]
            + [str(s.get("uses", "")) for s in steps(job)]
        )
        if (name, job_name) != ("firmware-main", "publish"):
            assert "secrets." not in body, f"{name}:{job_name} must receive no secrets"
            assert "GITHUB_TOKEN" not in body


# ---------------------------------------------------------------------------
# firmware-main specifics
# ---------------------------------------------------------------------------


def test_main_builds_the_event_sha_and_publishes_only_on_canonical_push() -> None:
    """CI-T05 / CI-T06 preconditions."""
    workflow = load("firmware-main")
    on = triggers(workflow)
    assert on["push"]["branches"] == ["main"]
    for check in STABLE_CHECKS:
        checkout = steps(workflow["jobs"][check])[0]
        assert checkout["with"]["ref"] == "${{ github.sha }}"
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == list(STABLE_CHECKS)
    condition = " ".join(str(publish["if"]).split())
    assert "github.repository == 'Zensor-lab/vdog'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.event_name == 'push'" in condition
    assert "${{" not in str(publish["name"])


def test_main_never_promotes_a_pr_artifact() -> None:
    """CI-T05: only the publish job downloads, and only its own run's artifact."""
    workflow = load("firmware-main")
    for job_name, job in workflow["jobs"].items():
        refs = uses(job)
        downloads = [r for r in refs if "download-artifact@" in r]
        if job_name == "publish":
            assert len(downloads) == 1
        else:
            assert not downloads, f"{job_name} must rebuild from source"
    publish = workflow["jobs"]["publish"]
    download = next(s for s in steps(publish) if "download-artifact@" in str(s.get("uses")))
    assert download["with"]["run-id"] == "${{ github.run_id }}"
    assert download["with"]["repository"] == "${{ github.repository }}"
    assert download["with"]["name"] == "${{ needs.firmware-build.outputs.artifact-name }}"


def test_main_groups_per_sha_without_cancelling() -> None:
    """CI-T13: two rapid merges each keep their publish chance."""
    concurrency = load("firmware-main")["concurrency"]
    assert concurrency["group"] == "firmware-main-${{ github.sha }}"
    assert concurrency["cancel-in-progress"] is False


def test_main_publish_uses_the_tested_publish_module_with_the_event_sha() -> None:
    publish = load("firmware-main")["jobs"]["publish"]
    body = "\n".join(str(s.get("run", "")) for s in steps(publish))
    assert "python -m tools.firmware.publish" in body
    assert '--expected-sha "$GITHUB_SHA"' in body
    assert "python -m tools.firmware.validate_package" in body
    assert "sha256sum -c" in body
    assert "--allow-" not in body  # no bypass flag is ever passed


def test_main_package_job_checks_lockfiles() -> None:
    job = load("firmware-main")["jobs"]["firmware-package-tests"]
    body = "\n".join(str(s.get("run", "")) for s in steps(job))
    assert "git diff --exit-code -- firmware/dependencies.lock" in body
    assert "requirements-installer.lock" in body
    assert "--require-hashes" in body


def test_both_workflows_build_the_same_pinned_toolchain() -> None:
    pr, main = load("firmware-pr"), load("firmware-main")
    for check in STABLE_CHECKS:
        assert pr["jobs"][check]["runs-on"] == main["jobs"][check]["runs-on"]
        assert pr["jobs"][check]["timeout-minutes"] == main["jobs"][check]["timeout-minutes"]
    for name, workflow in (("firmware-pr", pr), ("firmware-main", main)):
        env = workflow["env"]
        assert env["VDOG_PYTHON"] == "3.12", name
        assert env["VDOG_PLATFORMIO_CORE"] == "6.2.0", name
        build = "\n".join(str(s.get("run", "")) for s in steps(workflow["jobs"]["firmware-build"]))
        assert "platformio==${VDOG_PLATFORMIO_CORE}" in build, name
        assert "pio run -d firmware -e vdog_xiao_sense_proto" in build, name
        assert "-t size" in build, name
        assert "requirements-dev.lock" in build, name


def test_workflow_source_records_ownership_boundaries() -> None:
    """The OWNER branch-protection decision stays documented, not asserted."""
    for name in WORKFLOWS:
        text = _RAW[name]
        assert "Branch protection" in text
        assert "OWNER" in text
