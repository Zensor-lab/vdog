"""Fake-adapter tests for the publish state machine (0.9.11-0.9.13).

Covers the master-plan 0.9.13 acceptance set: two rapid main SHAs, a
same-SHA rerun, an interrupted upload and conflicting existing tag/draft
states, plus the CI-T10/CI-T11/CI-T12/CI-T13 behaviours. No network, no
device, no GitHub credentials anywhere.
"""

from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import support
from tools.firmware import publish
from tools.firmware.contract import ContractError
from tools.firmware.publish import (
    GitHubAdapter,
    NoNetworkAdapter,
    PublishAborted,
    PublishConflict,
    Release,
    Asset,
    load_publish_inputs,
    publish as publish_run,
    publish_main,
)

MAIN_SHA_A = support.FULL_SHA_B                              # ...a1b2c3d
MAIN_SHA_B = "7aa96e66b0fa1b2c3d4e5f60718293a4b5c6d7e8"      # second main commit
TAG_A = f"firmware-main-{MAIN_SHA_A[:12]}"
TAG_B = f"firmware-main-{MAIN_SHA_B[:12]}"


# ---------------------------------------------------------------------------
# Fake GitHub adapter
# ---------------------------------------------------------------------------


class FakeGitHubAdapter(GitHubAdapter):
    """In-memory GitHub with exactly the adapter surface publish may use."""

    def __init__(
        self,
        *,
        tags: dict[str, str] | None = None,
        create_tag_target: str | None = None,
        fail_upload_on: int | None = None,
        downloadable: bool = True,
        fail_download_names: set[str] | None = None,
        published_release: Release | None = None,
        published_manifest_doc: dict[str, Any] | None = None,
    ) -> None:
        self.tags = dict(tags or {})
        self.releases: dict[str, Release] = {}
        self.assets: dict[int, list[Asset]] = {}
        self.asset_bytes: dict[int, bytes] = {}
        self.calls: list[str] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.uploads: list[tuple[int, str]] = []
        self.deleted: list[str] = []
        self.logs: list[str] = []
        self.create_tag_target = create_tag_target
        self.fail_upload_on = fail_upload_on
        self.downloadable = downloadable
        self.fail_download_names = fail_download_names
        self._release_id = 1000
        self._asset_id = 5000
        if published_release is not None:
            self.releases[published_release.tag_name] = published_release
            self.assets[published_release.id] = []
            if published_manifest_doc is not None:
                self._seed_published_assets(published_release, published_manifest_doc)

    # -- helpers -----------------------------------------------------------
    def _seed_published_assets(self, release: Release, manifest_doc: dict[str, Any]) -> None:
        names = ["vdog-xiao-sense-main-manifest.zip", "manifest.json"]
        for name in names:
            self._asset_id += 1
            asset = Asset(id=self._asset_id, name=name, size=2, download_url=f"mem://{name}")
            self.assets[release.id].append(asset)
            self.asset_bytes[asset.id] = (
                json.dumps(manifest_doc).encode("utf-8")
                if name == "manifest.json"
                else b"zip"
            )

    def seed_draft(self, tag: str, *, target_commitish: str | None, assets: list[str],
                   title: str = "stale", release_id: int = 777) -> Release:
        release = Release(
            id=release_id, tag_name=tag, draft=True, prerelease=True,
            make_latest="false", title=title, target_commitish=target_commitish,
        )
        self.releases[tag] = release
        self.assets[release_id] = []
        for name in assets:
            self._asset_id += 1
            asset = Asset(id=self._asset_id, name=name, size=1,
                          download_url=f"mem://{name}")
            self.assets[release_id].append(asset)
            self.asset_bytes[asset.id] = b"stale"
        return release

    def seed_published(self, tag: str, *, title: str, manifest_doc: dict[str, Any],
                       asset_names: list[str] | None = None, prerelease: bool = True,
                       make_latest: str = "false", release_id: int = 888) -> Release:
        release = Release(
            id=release_id, tag_name=tag, draft=False, prerelease=prerelease,
            make_latest=make_latest, title=title, target_commitish=None,
        )
        self.releases[tag] = release
        self.assets[release_id] = []
        for name in (asset_names or ["manifest.json"]):
            self._asset_id += 1
            asset = Asset(id=self._asset_id, name=name, size=1,
                          download_url=f"mem://{tag}/{name}")
            self.assets[release_id].append(asset)
            self.asset_bytes[asset.id] = (
                json.dumps(manifest_doc).encode("utf-8") if name == "manifest.json"
                else b"published"
            )
        return release

    def asset_names(self, release_id: int) -> list[str]:
        return sorted(asset.name for asset in self.assets.get(release_id, []))

    def asset_data(self, release_id: int, name: str) -> bytes | None:
        for asset in self.assets.get(release_id, []):
            if asset.name == name:
                return self.asset_bytes.get(asset.id)
        return None

    def mutating_calls(self) -> list[str]:
        return [c for c in self.calls if c.split()[0] in ("POST", "PATCH", "DELETE")]

    def release_mutations(self) -> list[str]:
        """Mutating calls that could rewrite a release or its assets."""
        return [c for c in self.mutating_calls()
                if "release" in c or "asset" in c]

    # -- GitHubAdapter surface --------------------------------------------
    def log(self, message: str) -> None:
        self.logs.append(message)

    def get_tag(self, tag: str) -> str | None:
        self.calls.append(f"GET tag {tag}")
        return self.tags.get(tag)

    def create_tag(self, *, tag: str, sha: str, message: str) -> None:
        self.calls.append(f"POST tag {tag}@{sha}")
        self.created.append({"tag": tag, "sha": sha, "message": message})
        self.tags[tag] = self.create_tag_target or sha

    def get_release_by_tag(self, tag: str) -> Release | None:
        self.calls.append(f"GET release {tag}")
        return self.releases.get(tag)

    def create_release(self, **kwargs: Any) -> Release:
        self.calls.append(f"POST release {kwargs['tag']}")
        self.created.append({"release": kwargs})
        self._release_id += 1
        release = Release(
            id=self._release_id,
            tag_name=kwargs["tag"],
            draft=kwargs["draft"],
            prerelease=kwargs["prerelease"],
            make_latest=kwargs["make_latest"],
            title=kwargs["title"],
            target_commitish=kwargs["target_sha"],
        )
        self.releases[kwargs["tag"]] = release
        self.assets[release.id] = []
        return release

    def update_release(self, release_id: int, **kwargs: Any) -> Release:
        self.calls.append(f"PATCH release {release_id} draft={kwargs['draft']}")
        self.updated.append({"release_id": release_id, **kwargs})
        for tag, release in list(self.releases.items()):
            if release.id == release_id:
                updated = Release(
                    id=release.id, tag_name=release.tag_name,
                    draft=kwargs["draft"], prerelease=kwargs["prerelease"],
                    make_latest=kwargs["make_latest"], title=kwargs["title"],
                    target_commitish=release.target_commitish,
                    assets=tuple(self.assets.get(release_id, [])),
                )
                self.releases[tag] = updated
                return updated
        raise AssertionError(f"unknown release {release_id}")

    def list_assets(self, release_id: int) -> tuple[Asset, ...]:
        self.calls.append(f"GET assets {release_id}")
        return tuple(self.assets.get(release_id, []))

    def upload_asset(self, release_id: int, asset) -> Asset:
        self.calls.append(f"POST asset {asset.name}")
        self.uploads.append((release_id, asset.name))
        if self.fail_upload_on is not None and len(self.uploads) == self.fail_upload_on:
            raise RuntimeError("simulated transport interruption")
        self._asset_id += 1
        stored = Asset(id=self._asset_id, name=asset.name, size=asset.size,
                       download_url=f"mem://{release_id}/{asset.name}")
        self.assets.setdefault(release_id, []).append(stored)
        self.asset_bytes[stored.id] = asset.data
        return stored

    def delete_asset(self, asset: Asset) -> None:
        self.calls.append(f"DELETE asset {asset.name}")
        self.deleted.append(asset.name)
        for bucket in self.assets.values():
            for index, item in enumerate(bucket):
                if item.id == asset.id:
                    del bucket[index]
                    break
        self.asset_bytes.pop(asset.id, None)

    def download_asset(self, asset: Asset) -> bytes | None:
        self.calls.append(f"GET asset-bytes {asset.name}")
        if not self.downloadable:
            return None
        if self.fail_download_names and asset.name in self.fail_download_names:
            return None
        return self.asset_bytes.get(asset.id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def build_main_package(
    tmp_path: Path,
    *,
    sha: str = MAIN_SHA_A,
    run_id: int = 4242,
    attempt: int = 1,
) -> tuple[Path, Path, dict[str, Any]]:
    """A genuine main-kind package ZIP (+ .sha256) and its manifest."""
    zip_path, sha_path, payload, manifest = support.package_from_build_dir(
        tmp_path / f"pkg-{sha[:12]}",
        metadata_path=support.write_metadata(tmp_path / f"meta-{sha[:12]}", kind="main",
                                            sha=sha),
        run_id=run_id,
        attempt=attempt,
    )
    assert manifest["source"]["sha"] == sha
    return zip_path, sha_path, manifest


def publish_kwargs(zip_path: Path, sha: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "expected_sha": sha,
        "repo": publish.DEFAULT_REPO,
        "ref": publish.EXPECTED_REF,
        "event_name": publish.EXPECTED_EVENT,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Local validation happens before any network object exists (CI-07)
# ---------------------------------------------------------------------------


def test_wrong_expected_sha_is_refused_before_any_call(tmp_path: Path) -> None:
    zip_path, _sha_path, _manifest = build_main_package(tmp_path)
    adapter = FakeGitHubAdapter()
    with pytest.raises(ContractError) as exc:
        publish_main(zip_path, **publish_kwargs(zip_path, MAIN_SHA_B), adapter=adapter)
    assert any("!= expected main SHA" in e or "source.sha" in e for e in exc.value.errors)
    assert adapter.calls == []


def test_missing_external_digest_is_refused(tmp_path: Path) -> None:
    zip_path, sha_path, _manifest = build_main_package(tmp_path)
    sha_path.unlink()
    with pytest.raises(PublishAborted) as exc:
        load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    assert any(".sha256" in e for e in exc.value.errors)


def test_corrupt_zip_is_refused(tmp_path: Path) -> None:
    zip_path, sha_path, _manifest = build_main_package(tmp_path)
    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        tampered = {
            info.filename.split("/", 1)[1]: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    tampered["images/firmware.bin"] = tampered["images/firmware.bin"][:-16]
    # Re-resolving the hashes keeps the archive self-consistent, so the
    # external digest is what must catch the rebuild.
    support.rezip(zip_path, support.with_resolved_hashes(tampered))
    with pytest.raises(PublishAborted) as exc:
        load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    assert any(".sha256" in e for e in exc.value.errors)
    assert sha_path.is_file()


def test_malformed_expected_sha_is_refused(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    with pytest.raises(PublishAborted) as exc:
        load_publish_inputs(zip_path, expected_sha="deadbeef")
    assert any("40-hex" in e for e in exc.value.errors)


def test_local_package_identity_cannot_be_published(tmp_path: Path) -> None:
    zip_path, _sha_path, _payload, _manifest = support.package_from_build_dir(
        tmp_path / "local"
    )
    with pytest.raises(PublishAborted) as exc:
        load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    assert any("only main builds are publishable" in e for e in exc.value.errors)


def test_adapter_has_no_tag_mutation_surface() -> None:
    """Immutability is structural: the adapter protocol cannot move a tag."""
    forbidden = ("delete_tag", "update_tag", "move_tag", "force", "delete_ref",
                 "update_ref", "delete_release", "merge")
    names = [name for name in dir(GitHubAdapter) if not name.startswith("_")]
    assert names, "adapter protocol must expose an explicit surface"
    for name in names:
        for forbidden_name in forbidden:
            assert forbidden_name not in name.lower(), (name, forbidden_name)


def test_no_network_adapter_blocks_every_mutation(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = NoNetworkAdapter(log=lambda _m: None)
    assert adapter.get_tag(inputs.tag) is None
    assert adapter.get_release_by_tag(inputs.tag) is None
    assert adapter.list_assets(1) == ()
    for call in (
        lambda: adapter.create_tag(tag=inputs.tag, sha=inputs.full_sha, message="x"),
        lambda: adapter.create_release(tag=inputs.tag, target_sha=inputs.full_sha,
                                       title="t", body="b", draft=True,
                                       prerelease=True, make_latest="false"),
        lambda: adapter.update_release(1, title="t", body="b", draft=False,
                                       prerelease=True, make_latest="false"),
        lambda: adapter.upload_asset(1, inputs.assets[0]),
        lambda: adapter.delete_asset(Asset(id=1, name="x", size=1)),
    ):
        with pytest.raises(PublishAborted):
            call()
    assert len(adapter.attempted_mutations) == 5


# ---------------------------------------------------------------------------
# Happy path: create tag, draft, upload, publish (0.9.11/0.9.12)
# ---------------------------------------------------------------------------


def test_publish_creates_verified_tag_and_complete_release(tmp_path: Path) -> None:
    zip_path, _sha_path, manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter()
    report = publish_run(adapter, inputs)

    assert report.decision == "published-new"
    assert report.tag_action == "created"
    assert report.tag == TAG_A
    assert report.target_sha == MAIN_SHA_A
    assert report.title == f"vdog 0.2.0-proto \u2014 main {MAIN_SHA_A[:12]}"

    tag_creation = next(c for c in adapter.created if "tag" in c)
    assert tag_creation["sha"] == MAIN_SHA_A
    assert f"build_id: main-{MAIN_SHA_A[:12]}" in tag_creation["message"]
    assert f"version: {manifest['firmware_version']}" in tag_creation["message"]
    assert "run_id: 4242" in tag_creation["message"]

    release_creation = next(c for c in adapter.created if "release" in c)["release"]
    assert release_creation["draft"] is True          # draft FIRST, always
    assert release_creation["tag"] == TAG_A
    assert release_creation["target_sha"] == MAIN_SHA_A  # never a branch name
    assert release_creation["prerelease"] is True
    assert release_creation["make_latest"] == "false"
    assert release_creation["title"] == report.title

    final = adapter.releases[TAG_A]
    assert final.draft is False
    assert final.prerelease is True
    assert final.make_latest == "false"
    assert adapter.asset_names(final.id) == sorted(inputs.asset_names)
    assert set(inputs.asset_names) == {
        f"vdog-xiao-sense-main-{MAIN_SHA_A[:12]}.zip",
        f"vdog-xiao-sense-main-{MAIN_SHA_A[:12]}.zip.sha256",
        "INSTALL.md",
        "RELEASE_NOTES.md",
        "THIRD_PARTY_NOTICES.md",
        "manifest.json",
    }
    # The published ZIP bytes are exactly the locally validated build.
    assert adapter.asset_data(final.id, inputs.zip_name) == zip_path.read_bytes()
    assert adapter.asset_data(final.id, inputs.zip_name + ".sha256") == (
        f"{inputs.zip_sha256}  {inputs.zip_name}\n".encode("utf-8")
    )
    # Draft -> assets -> publish ordering is enforced by the recorded calls.
    order = [c for c in adapter.calls if c.startswith(("POST", "PATCH", "DELETE"))]
    assert order[0].startswith("POST tag")
    assert order[1].startswith("POST release")
    assert order[-1].startswith(f"PATCH release {final.id} draft=False")
    assert all(c.startswith("POST asset") for c in order[2:-1])


def test_tag_peel_mismatch_stops_before_release(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(create_tag_target=MAIN_SHA_B)  # remote peeled elsewhere
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    assert any("peeled" in e for e in exc.value.errors)
    assert not any(c.startswith("POST release") for c in adapter.calls)


# ---------------------------------------------------------------------------
# Idempotent rerun / never overwrite (CI-T10, 0.9.13)
# ---------------------------------------------------------------------------


def test_same_sha_rerun_reuses_the_published_release(tmp_path: Path) -> None:
    zip_path, _sha, manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter()
    first = publish_run(adapter, inputs)
    calls_after_first = list(adapter.calls)

    second = publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    assert second.decision == "reused-published"
    assert second.release_id == first.release_id
    new_calls = adapter.calls[len(calls_after_first):]
    assert [c.split()[0] for c in new_calls] == ["GET"] * len(new_calls)
    assert not [c for c in new_calls if c.startswith(("POST", "PATCH", "DELETE"))]


def test_rerun_from_a_newer_run_reuses_published_ci_identity(tmp_path: Path) -> None:
    """Reruns have different ci run/attempt and may differ byte-wise; the
    published *manifest identity* decides, not byte equality (0.9.13)."""
    zip_a, _sha_a, manifest_a = build_main_package(tmp_path, run_id=1, attempt=1)
    adapter = FakeGitHubAdapter()
    publish_run(adapter, load_publish_inputs(zip_a, expected_sha=MAIN_SHA_A))

    zip_b, _sha_b, manifest_b = build_main_package(
        tmp_path / "rerun", run_id=99, attempt=3
    )
    assert manifest_b["ci"] != manifest_a["ci"]
    report = publish_run(adapter, load_publish_inputs(zip_b, expected_sha=MAIN_SHA_A))
    assert report.decision == "reused-published"
    assert report.release_action.startswith("reused")


def test_published_release_with_foreign_manifest_is_a_conflict(tmp_path: Path) -> None:
    zip_path, _sha, manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    foreign = copy.deepcopy(manifest)
    foreign["build_id"] = "main-000000000000"
    foreign["tag"] = "firmware-main-000000000000"
    release = Release(id=900, tag_name=TAG_A, draft=False, prerelease=True,
                      make_latest="false", title=inputs.title, target_commitish=None)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_A},
                               published_release=release,
                               published_manifest_doc=foreign)
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    assert any("already published manifest disagrees" in e for e in exc.value.errors)
    assert adapter.mutating_calls() == []


def test_published_release_missing_an_asset_is_a_conflict(tmp_path: Path) -> None:
    zip_path, _sha, manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    release = Release(id=901, tag_name=TAG_A, draft=False, prerelease=True,
                      make_latest="false", title=inputs.title)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_A},
                               published_release=release,
                               published_manifest_doc=manifest)
    # Seed only the manifest: the ZIP/notes assets are missing.
    adapter.assets[release.id] = [a for a in adapter.assets[release.id]
                                 if a.name == "manifest.json"]
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    assert any("never repaired in place" in e for e in exc.value.errors)
    assert adapter.mutating_calls() == []


def test_published_release_without_prototype_flags_is_rejected(tmp_path: Path) -> None:
    zip_path, _sha, manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    release = Release(id=902, tag_name=TAG_A, draft=False, prerelease=False,
                      make_latest="true", title=inputs.title)
    adapter = FakeGitHubAdapter(published_release=release, published_manifest_doc=manifest)
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    messages = " ".join(exc.value.errors)
    assert "prerelease" in messages and "make_latest" in messages


def test_unreadable_published_manifest_asset_warns_but_zip_always_verified(
    tmp_path: Path,
) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    adapter = FakeGitHubAdapter()
    report = publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    assert report.decision == "published-new"

    # Nothing is downloadable: the ZIP cannot be verified at all, so a rerun
    # is REFUSED outright (P1-3) — an unverified ZIP is never "reused".
    adapter.downloadable = False
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    assert "could not be downloaded" in " ".join(exc.value.errors)
    adapter.downloadable = True

    # The ZIP and its sidecar verify, but the standalone manifest.json asset
    # cannot be downloaded: the manifest-identity step degrades to a warning
    # and the ZIP's OWN embedded manifest is still identity-checked.
    adapter.fail_download_names = {"manifest.json"}
    report = publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    assert report.decision == "reused-published"
    assert any("could not be downloaded" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# P1-3: the existing Release ZIP must verify before a rerun reports reuse
# ---------------------------------------------------------------------------


def _publish_once(tmp_path: Path) -> tuple[FakeGitHubAdapter, Any, Path]:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    adapter = FakeGitHubAdapter()
    report = publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    return adapter, report, zip_path


def _stored_zip_asset(adapter: FakeGitHubAdapter, release_id: int) -> Asset:
    for asset in adapter.assets[release_id]:
        if asset.name.endswith(".zip"):
            return asset
    raise AssertionError("published ZIP asset not seeded")


def _sidecar_asset(adapter: FakeGitHubAdapter, release_id: int) -> Asset:
    for asset in adapter.assets[release_id]:
        if asset.name.endswith(".zip.sha256"):
            return asset
    raise AssertionError("published sidecar asset not seeded")


def test_rerun_rejects_a_tampered_published_zip(tmp_path: Path) -> None:
    """Published ZIP bytes no longer match the published detached digest."""
    adapter, report, zip_path = _publish_once(tmp_path)
    zip_asset = _stored_zip_asset(adapter, report.release_id)
    flipped = bytearray(adapter.asset_bytes[zip_asset.id])
    flipped[len(flipped) // 2] ^= 0xFF
    adapter.asset_bytes[zip_asset.id] = bytes(flipped)
    mutating_before = list(adapter.mutating_calls())

    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    messages = " ".join(exc.value.errors)
    assert "does not match its detached digest" in messages
    assert "reuse refused" in messages
    # The refused rerun mutated nothing.
    assert adapter.mutating_calls() == mutating_before


def test_rerun_rejects_rehashed_but_internally_inconsistent_zip(tmp_path: Path) -> None:
    """Even with the sidecar recomputed to match, an internally tampered ZIP
    (images no longer match their manifest digests) is rejected on rerun."""
    adapter, report, zip_path = _publish_once(tmp_path)
    payload = support._payload_from_zip(zip_path)
    tampered = bytearray(payload["images/firmware.bin"])
    tampered[64] ^= 0xFF
    payload["images/firmware.bin"] = bytes(tampered)
    # Re-sign ONLY the external sidecar (internal manifest digests now lie).
    forged_zip = support.rezip(Path(str(zip_path) + ".forged.zip"), payload,
                               build_id=json.loads(
                                   payload["manifest.json"].decode())["build_id"])
    # rezip rewrote payload entries unchanged apart from our flip; recompute
    # only the detached digest to match the forged bytes.
    forged_bytes = forged_zip.read_bytes()
    sidecar = _sidecar_asset(adapter, report.release_id)
    adapter.asset_bytes[sidecar.id] = (
        f"{support.sha256_bytes(forged_bytes)}  {sidecar.name[:-len('.sha256')]}\n"
    ).encode()
    zip_asset = _stored_zip_asset(adapter, report.release_id)
    adapter.asset_bytes[zip_asset.id] = forged_bytes

    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    messages = " ".join(exc.value.errors)
    assert "fails package validation for reuse" in messages


def test_rerun_rejects_embedded_manifest_identity_mismatch(tmp_path: Path) -> None:
    """A ZIP whose internal manifest is consistently re-signed but carries a
    DIFFERENT release identity than the tag/release must be rejected."""
    adapter, report, zip_path = _publish_once(tmp_path)
    payload = support._payload_from_zip(zip_path)
    doc = json.loads(payload["manifest.json"].decode("utf-8"))
    doc["build_id"] = "main-000000000000"
    doc["tag"] = "firmware-main-000000000000"
    doc["source"]["sha"] = "0" * 40
    doc["source"]["sha_short"] = "0" * 12
    payload["manifest.json"] = (json.dumps(doc, sort_keys=True, indent=2,
                                           ensure_ascii=False) + "\n").encode()
    version = json.loads(payload["VERSION.json"].decode("utf-8"))
    for key, value in (
        ("build_id", doc["build_id"]), ("source_sha", doc["source"]["sha"]),
        ("source_sha_short", doc["source"]["sha_short"]), ("tag", doc["tag"]),
    ):
        if key in version:
            version[key] = value
    payload["VERSION.json"] = (json.dumps(version, sort_keys=True, indent=2,
                                          ensure_ascii=False) + "\n").encode()
    # Everything EXCEPT the identity is re-resolved to consistency, so the
    # only fault left for the reuse gate to catch is the identity itself.
    payload = support.with_resolved_hashes(payload)
    forged_zip = support.rezip(Path(str(zip_path) + ".forged2.zip"), payload,
                               build_id="main-000000000000")
    forged_bytes = forged_zip.read_bytes()
    zip_asset = _stored_zip_asset(adapter, report.release_id)
    adapter.asset_bytes[zip_asset.id] = forged_bytes
    sidecar = _sidecar_asset(adapter, report.release_id)
    adapter.asset_bytes[sidecar.id] = (
        f"{support.sha256_bytes(forged_bytes)}  {zip_asset.name}\n").encode()

    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    messages = " ".join(exc.value.errors)
    assert "embedded in the published ZIP disagrees" in messages


@pytest.mark.parametrize("missing", [
    pytest.param("zip", id="zip-undownloadable"),
    pytest.param("sidecar", id="sidecar-undownloadable"),
])
def test_rerun_refuses_an_unverifiable_published_zip(tmp_path: Path, missing: str) -> None:
    """No download, no verification, no reuse: each unverifiable asset alone
    turns the rerun into a hard failure instead of a warning."""
    adapter, report, zip_path = _publish_once(tmp_path)
    names: set[str] = set()
    for asset in adapter.assets[report.release_id]:
        if missing == "zip" and asset.name.endswith(".zip"):
            names.add(asset.name)
        if missing == "sidecar" and asset.name.endswith(".zip.sha256"):
            names.add(asset.name)
    adapter.fail_download_names = names
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A))
    messages = " ".join(exc.value.errors)
    assert "could not be downloaded" in messages


# ---------------------------------------------------------------------------
# Tag conflicts (CI-T10)
# ---------------------------------------------------------------------------


def test_existing_tag_at_other_target_is_a_hard_failure(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_B})
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    assert any("immutable" in e for e in exc.value.errors)
    assert adapter.mutating_calls() == []
    assert not any("release" in c for c in adapter.calls)


def test_existing_matching_tag_is_reused(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_A})
    report = publish_run(adapter, inputs)
    assert report.tag_action == "reused"
    assert not any(c.startswith("POST tag") for c in adapter.calls)


# ---------------------------------------------------------------------------
# Draft repair and interrupted uploads (0.9.13)
# ---------------------------------------------------------------------------


def test_partial_draft_asset_set_is_replaced_wholesale(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter()
    adapter.seed_draft(TAG_A, target_commitish=MAIN_SHA_A,
                       assets=["old-build.zip", "INSTALL.md"])
    report = publish_run(adapter, inputs)
    assert report.decision == "published-repaired-draft"
    assert sorted(adapter.deleted) == ["INSTALL.md", "old-build.zip"]
    assert adapter.asset_names(report.release_id) == sorted(inputs.asset_names)
    assert adapter.asset_data(report.release_id, inputs.zip_name) == zip_path.read_bytes()


def test_draft_reporting_a_branch_target_is_still_repaired(tmp_path: Path) -> None:
    """0.9.13 interrupted-rerun recovery must survive GitHub's normalisation.

    GitHub frequently reports ``target_commitish`` as the default branch for a
    release created against an existing tag. The bound tag is verified against
    the tested SHA and the tool cannot move it, so this is a warning — not a
    conflict that would strand the draft forever (the adapter has no delete).
    """
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_A})
    adapter.seed_draft(TAG_A, target_commitish="main", assets=["partial.zip"])
    report = publish_run(adapter, inputs)
    assert report.decision == "published-repaired-draft"
    assert any("target_commitish" in w and "main" in w for w in report.warnings)
    assert adapter.asset_names(report.release_id) == sorted(inputs.asset_names)
    assert "partial.zip" not in adapter.asset_names(report.release_id)
    assert adapter.releases[TAG_A].draft is False


def test_draft_for_the_wrong_tag_is_still_a_hard_conflict(tmp_path: Path) -> None:
    """The warning above must not soften the one field that really matters."""
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(tags={TAG_A: MAIN_SHA_A})
    release = adapter.seed_draft(TAG_A, target_commitish=MAIN_SHA_A, assets=[])
    adapter.releases[TAG_A] = Release(
        id=release.id, tag_name="firmware-main-000000000000", draft=True,
        prerelease=True, make_latest="false", title="stale",
        target_commitish=inputs.full_sha,
    )
    with pytest.raises(PublishConflict) as exc:
        publish_run(adapter, inputs)
    assert any("targets tag" in e for e in exc.value.errors)
    assert adapter.uploads == []


def test_draft_for_a_different_tag_is_never_reused(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter()
    adapter.seed_draft("firmware-main-deadbeefdead", target_commitish=MAIN_SHA_A,
                       assets=[])
    # get_release_by_tag(TAG_A) never returns it, so publish creates its own.
    report = publish_run(adapter, inputs)
    assert report.decision == "published-new"
    assert list(adapter.releases) == ["firmware-main-deadbeefdead", TAG_A]


def test_interrupted_upload_leaves_a_repairable_draft(tmp_path: Path) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter(fail_upload_on=3)
    with pytest.raises(PublishAborted) as exc:
        publish_run(adapter, inputs)
    text = " ".join(exc.value.errors)
    assert "interrupted after 2/6 assets" in text
    assert "repairable" in text
    release = adapter.releases[TAG_A]
    assert release.draft is True                      # never half-published
    assert adapter.updated == []                      # no publish attempt
    assert len(adapter.uploads) == 3

    # The next attempt replaces the whole set: nothing from the interrupted
    # attempt survives and the release completes.
    adapter.fail_upload_on = None
    stale_before = [a.name for a in adapter.assets[release.id]]
    report = publish_run(adapter, inputs)
    assert report.decision == "published-repaired-draft"
    assert adapter.deleted[-len(stale_before):] == stale_before
    assert adapter.asset_names(release.id) == sorted(inputs.asset_names)
    assert adapter.releases[TAG_A].draft is False


def test_two_rapid_main_commits_get_independent_releases(tmp_path: Path) -> None:
    zip_a, _sha_a, manifest_a = build_main_package(tmp_path, sha=MAIN_SHA_A)
    zip_b, _sha_b, manifest_b = build_main_package(tmp_path, sha=MAIN_SHA_B)
    assert manifest_a["build_id"] != manifest_b["build_id"]

    adapter = FakeGitHubAdapter()
    report_a = publish_run(adapter, load_publish_inputs(zip_a, expected_sha=MAIN_SHA_A))
    report_b = publish_run(adapter, load_publish_inputs(zip_b, expected_sha=MAIN_SHA_B))

    assert (report_a.tag, report_b.tag) == (TAG_A, TAG_B)
    assert adapter.tags[TAG_A] == MAIN_SHA_A and adapter.tags[TAG_B] == MAIN_SHA_B
    assert report_a.release_id != report_b.release_id
    assert adapter.asset_names(report_a.release_id) == sorted(
        load_publish_inputs(zip_a, expected_sha=MAIN_SHA_A).asset_names
    )
    assert adapter.asset_data(report_a.release_id, f"vdog-xiao-sense-main-{MAIN_SHA_A[:12]}.zip") \
        == zip_a.read_bytes()
    assert adapter.asset_data(report_b.release_id, f"vdog-xiao-sense-main-{MAIN_SHA_B[:12]}.zip") \
        == zip_b.read_bytes()
    # Neither release ever saw the other build's assets.
    assert all("main-" not in name or MAIN_SHA_A[:12] in name
               for name in adapter.asset_names(report_a.release_id))
    assert all(MAIN_SHA_B[:12] in name or not name.endswith(".zip")
               for name in adapter.asset_names(report_b.release_id))


# ---------------------------------------------------------------------------
# Canonical-main / event guards (CI-T13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"repo": "evil/fork"}, "canonical"),
        ({"ref": "refs/heads/feature"}, "refs/heads/main"),
        ({"event_name": "pull_request"}, "pull_request"),
        ({"event_name": "workflow_dispatch"}, "workflow_dispatch"),
    ],
)
def test_publish_context_guard_refuses(tmp_path: Path, overrides: dict[str, str],
                                       needle: str) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    adapter = FakeGitHubAdapter()
    with pytest.raises(PublishConflict) as exc:
        publish_main(zip_path, **publish_kwargs(zip_path, MAIN_SHA_A, **overrides),
                     adapter=adapter)
    assert needle in " ".join(exc.value.errors)
    assert adapter.calls == []


def test_publish_context_guard_accepts_canonical_push() -> None:
    publish.check_publish_context(repo=publish.DEFAULT_REPO, ref=publish.EXPECTED_REF,
                                 event_name=publish.EXPECTED_EVENT)


# ---------------------------------------------------------------------------
# Dry run performs no network calls and no mutation
# ---------------------------------------------------------------------------


def test_dry_run_refuses_any_adapter_that_could_mutate(tmp_path: Path) -> None:
    """A dry run is structurally mutation-free, not just politely so."""
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    inputs = load_publish_inputs(zip_path, expected_sha=MAIN_SHA_A)
    adapter = FakeGitHubAdapter()
    with pytest.raises(PublishAborted) as exc:
        publish_run(adapter, inputs, dry_run=True)
    assert "NoNetworkAdapter" in " ".join(exc.value.errors)
    assert adapter.calls == []


def test_dry_run_makes_no_mutation_and_no_rest_adapter(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    calls: list[str] = []

    def explode(*_a: Any, **_k: Any) -> None:
        calls.append("RestGitHubAdapter constructed")
        raise AssertionError("dry run must not construct the REST adapter")

    monkeypatch.setattr(publish, "RestGitHubAdapter", explode)
    report = publish_main(zip_path, **publish_kwargs(zip_path, MAIN_SHA_A), dry_run=True)
    assert report.decision == "dry-run"
    assert calls == []
    assert report.tag_action == "would create"
    assert report.asset_names and report.release_id is None
    assert any("no network calls" in line for line in report.actions)


def test_dry_run_cli_returns_zero_without_network(tmp_path: Path, capsys) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    code = publish._main([  # noqa: SLF001 - CLI is the documented interface
        "--zip", str(zip_path),
        "--expected-sha", MAIN_SHA_A,
        "--repo", publish.DEFAULT_REPO,
        "--ref", publish.EXPECTED_REF,
        "--event-name", publish.EXPECTED_EVENT,
        "--dry-run",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "publish: dry-run" in out
    assert "manifest.json" in out
    assert f"vdog 0.2.0-proto \u2014 main {MAIN_SHA_A[:12]}" in out


def test_cli_reports_failure_without_traceback(tmp_path: Path, capsys) -> None:
    zip_path, _sha, _manifest = build_main_package(tmp_path)
    code = publish._main([  # noqa: SLF001
        "--zip", str(zip_path),
        "--expected-sha", MAIN_SHA_B,
        "--repo", publish.DEFAULT_REPO,
        "--ref", publish.EXPECTED_REF,
        "--event-name", publish.EXPECTED_EVENT,
    ])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_rest_adapter_requires_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(PublishAborted) as exc:
        publish.RestGitHubAdapter(repo=publish.DEFAULT_REPO)
    assert any("GITHUB_TOKEN" in e for e in exc.value.errors)


# ---------------------------------------------------------------------------
# REST adapter internals (transport hardening, no live network)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),
        ("", None),
        ('<https://api.github.com/a?page=2>; rel="next"', "https://api.github.com/a?page=2"),
        ('<https://api.github.com/a?page=2>; rel=next', "https://api.github.com/a?page=2"),
        ('<https://api.github.com/a?page=1>; rel="prev", '
         '<https://api.github.com/a?page=2>; rel="next"', "https://api.github.com/a?page=2"),
        ('<https://api.github.com/a?page=3>; rel="last"', None),
        ('<>; rel="next"', None),
        ('garbage', None),
    ],
)
def test_next_page_url_parses_the_link_header(header: str | None,
                                              expected: str | None) -> None:
    assert publish.next_page_url(header) == expected


class _StubRestAdapter(publish.RestGitHubAdapter):
    """RestGitHubAdapter with the HTTP layer replaced by canned responses."""

    def __init__(self, pages: list[tuple[list[dict[str, Any]], dict[str, str]]]) -> None:
        super().__init__(repo=publish.DEFAULT_REPO, token="t", log=lambda _m: None)
        self.pages = pages
        self.seen: list[str] = []

    def _request(self, method: str, url: str, **_kw: Any) -> tuple[int, bytes, dict[str, str]]:
        assert method == "GET"
        self.seen.append(url)
        if not self.pages:
            raise AssertionError(f"unexpected extra request to {url}")
        items, headers = self.pages.pop(0)
        return 200, json.dumps(items).encode("utf-8"), headers


def test_list_assets_follows_pagination() -> None:
    """A >100-asset draft must be enumerated fully, not page 1 only."""
    page1 = [{"id": i, "name": f"a{i}.bin", "size": 1} for i in range(100)]
    page2 = [{"id": 100 + i, "name": f"b{i}.bin", "size": 1} for i in range(6)]
    adapter = _StubRestAdapter([
        (page1, {"Link": '<https://api.github.com/x?page=2>; rel="next"'}),
        (page2, {}),
    ])
    assets = adapter.list_assets(7)
    assert [a.name for a in assets][:2] == ["a0.bin", "a1.bin"]
    assert len(assets) == 106
    assert assets[-1].name == "b5.bin"
    assert len(adapter.seen) == 2          # no third page requested


def test_list_assets_refuses_to_run_out_of_pages_silently() -> None:
    pages = [([{ "id": i, "name": f"a{i}", "size": 1} for i in range(3)],
              {"Link": '<https://api.github.com/x?page=n>; rel="next"'})
             for _ in range(60)]
    adapter = _StubRestAdapter(pages)
    with pytest.raises(publish.GitHubApiError) as exc:
        adapter.list_assets(7)
    assert "did not finish paginating" in " ".join(exc.value.errors)


def test_api_errors_carry_the_status_and_only_404_means_absent() -> None:
    gone = publish.GitHubApiError(["nope"], status=404)
    forbidden = publish.GitHubApiError(["nope"], status=403)
    plain = publish.PublishAborted(["nope"])
    assert publish._is_not_found(gone) is True          # noqa: SLF001
    assert publish._is_not_found(forbidden) is False    # noqa: SLF001
    assert publish._is_not_found(plain) is False        # noqa: SLF001
    assert gone.status == 404 and forbidden.status == 403


def _redirect(from_url: str, to_url: str) -> urllib.request.Request:
    request = urllib.request.Request(from_url, method="GET")
    request.add_header("Authorization", "Bearer super-secret")
    request.add_header("Accept", "application/vnd.github+json")
    return publish._TokenPinnedRedirectHandler().redirect_request(  # noqa: SLF001
        request, None, 302, "Found", {}, to_url
    )


def test_token_never_follows_a_cross_host_redirect() -> None:
    """urllib re-sends Authorization on redirect; publish must not."""
    same = _redirect("https://api.github.com/repos/x/y", "https://api.github.com/repos/z")
    assert same is not None and same.has_header("Authorization")
    assert same.full_url == "https://api.github.com/repos/z"

    cross = _redirect("https://api.github.com/repos/x/y",
                      "https://evil.example.com/collect")
    assert cross is not None
    assert not cross.has_header("Authorization")
    # The legitimate asset-download hop to blob storage still works, unsigned.
    blob = _redirect("https://api.github.com/repos/x/y",
                     "https://objects.githubusercontent.com/asset/1")
    assert blob is not None and not blob.has_header("Authorization")
