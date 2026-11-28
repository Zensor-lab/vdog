"""Immutable tag + GitHub Release publish state machine (0.9.11-0.9.13).

The trusted ``main`` workflow calls this module; it owns every publish
decision so the state logic is unit-testable behind a fake adapter. The
workflow file itself only installs the pinned toolchain, re-validates the
artifact and invokes ``python -m tools.firmware.publish``.

Guarantees implemented here (master plan 0.9.11-0.9.13, CI-04/CI-07,
CI-T10/CI-T11/CI-T12/CI-T13):

* the tag name is always ``firmware-main-<sha12>`` and it is created at the
  **full tested main SHA** as an annotated tag whose peeled target is
  re-read and verified;
* an existing tag is reused only on an exact target match; a different
  target is a visible hard failure. The adapter protocol exposes no tag
  update/delete/force-push operation at all, so no code path here can move
  or delete an immutable tag;
* a release is always created as a **draft** bound to the already verified
  tag (never to a branch name), gets its complete validated asset set, and
  is only then marked published; ``prerelease`` stays true and
  ``make_latest`` stays ``false``;
* a completed matching published release is reused only after its ZIP has
  been RE-VERIFIED: the ZIP bytes must hash to the published detached digest,
  pass package validation, and carry the verified release identity in their
  embedded manifest; the published ``.sha256`` must be the canonical single
  ``shasum -a 256`` line naming the release ZIP exactly, and the standalone
  ``manifest.json`` asset — downloaded exactly once — must match the embedded
  manifest byte-for-byte; an un-downloadable (unverifiable) ZIP or manifest is
  a failure, never a silent "reused";
* an unpublished draft carrying a partial asset set from the same tag/source
  has its **entire** asset set replaced in one attempt (delete-all then
  upload-all, published only after the set verifies);
* an interrupted upload leaves a repairable draft plus an explicit failure —
  never a half-published release and never a mix of two builds;
* ``--dry-run`` performs no network calls and no mutation.

Specs: docs/plans/0.9-firmware-ci-release.md sections 3-4 and 0.9.11-0.9.13,
docs/plans/0.9-round2-assignment.md deliverables 5 and 6.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.firmware import contract
from tools.firmware.contract import ContractError, derive_tag, short_sha
from tools.firmware.package import package_root_name
from tools.firmware.validate_package import validate_package_bytes

# ---------------------------------------------------------------------------
# Canonical publish context (CI-T13: the publish job must be canonical-main)
# ---------------------------------------------------------------------------

#: Canonical repository. Override with ``--repo``/``VDOG_PUBLISH_REPO`` only
#: for a fork rehearsal; the default refuses to publish from any other
#: repository, including PR forks.
DEFAULT_REPO = "Zensor-lab/vdog"
EXPECTED_REF = "refs/heads/main"
EXPECTED_EVENT = "push"

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_UPLOAD_URL = "https://uploads.github.com"
DEFAULT_API_TIMEOUT_SECONDS = 60

#: Prototype bootstrap releases are pre-releases and never "latest"
#: (master plan 0.9.12; stable promotion needs separate product/device gates).
RELEASE_PRERELEASE = True
RELEASE_MAKE_LATEST = "false"

#: Title template from master plan section 3: ``vdog <version> — main <sha12>``.
TITLE_TEMPLATE = "vdog {version} \u2014 main {sha12}"

TAG_ANNOTATION_NAME = "vdog firmware release bot"
TAG_ANNOTATION_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
TAG_ANNOTATION_DATE = "1970-01-01T00:00:00Z"  # deterministic annotated tag

#: Manifest identity fields that must agree between the freshly built package
#: and an already published release. ``ci`` (run id/attempt) is deliberately
#: excluded: an authorised rerun is a different run of the same source.
PUBLISHED_MANIFEST_IDENTITY_FIELDS: tuple[str, ...] = (
    "schema",
    "package_format_version",
    "product",
    "product_slug",
    "hardware_class",
    "board",
    "environment",
    "target",
    "expected_flash_bytes",
    "firmware_version",
    "release_channel",
    "hardware_verified",
    "recording_available",
    "device_ota_available",
    "build_id",
    "tag",
)
PUBLISHED_SOURCE_IDENTITY_FIELDS: tuple[str, ...] = (
    "kind",
    "sha",
    "sha_short",
    "pr_number",
    "base_sha",
    "dirty",
)

class PublishConflict(ContractError):
    """A remote object disagrees with the requested immutable identity."""


class PublishAborted(ContractError):
    """Local validation or an interrupted operation prevented publishing."""


# ---------------------------------------------------------------------------
# Adapter data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Asset:
    """One Release asset (id/name/size are the only fields publish relies on)."""

    id: int
    name: str
    size: int
    download_url: str | None = None


@dataclass(frozen=True)
class Release:
    """The Release fields publish decides on (everything else is ignored)."""

    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    make_latest: str
    title: str
    target_commitish: str | None = None
    assets: tuple[Asset, ...] = ()


@dataclass(frozen=True)
class PublishAsset:
    """One asset publish intends to upload."""

    name: str
    data: bytes
    content_type: str

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class PublishInputs:
    """Everything publish needs, derived from one locally validated ZIP.

    ``assets`` is the single source of truth for the asset set: every entry
    comes out of the ZIP itself (never from the working tree), so an
    interrupted rebuild can never mix two builds into one Release.
    """

    full_sha: str
    build_id: str
    tag: str
    version: str
    title: str
    body: str
    zip_name: str
    zip_sha256: str
    manifest: dict[str, Any]
    assets: tuple[PublishAsset, ...]

    @property
    def asset_names(self) -> tuple[str, ...]:
        return tuple(asset.name for asset in self.assets)

    def asset(self, name: str) -> PublishAsset | None:
        for asset in self.assets:
            if asset.name == name:
                return asset
        return None


@dataclass
class PublishReport:
    """Structured outcome of one publish attempt (printed by the CLI)."""

    decision: str
    tag_action: str
    release_action: str
    release_id: int | None
    tag: str
    target_sha: str
    title: str
    asset_names: tuple[str, ...]
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "tag_action": self.tag_action,
            "release_action": self.release_action,
            "release_id": self.release_id,
            "tag": self.tag,
            "target_sha": self.target_sha,
            "title": self.title,
            "assets": list(self.asset_names),
            "actions": list(self.actions),
            "warnings": list(self.warnings),
        }


class GitHubAdapter:
    """Publish's whole view of GitHub.

    Deliberately minimal: there is no tag update, tag delete, force push or
    release delete method, so the immutability rules cannot be bypassed by
    any caller of this module. Tests provide a fake implementation.
    """

    def get_tag(self, tag: str) -> str | None:
        """Return the tag's peeled commit SHA, or None when absent."""
        raise NotImplementedError

    def create_tag(self, *, tag: str, sha: str, message: str) -> None:
        raise NotImplementedError

    def get_release_by_tag(self, tag: str) -> Release | None:
        raise NotImplementedError

    def create_release(
        self,
        *,
        tag: str,
        target_sha: str,
        title: str,
        body: str,
        draft: bool,
        prerelease: bool,
        make_latest: str,
    ) -> Release:
        raise NotImplementedError

    def update_release(
        self,
        release_id: int,
        *,
        title: str,
        body: str,
        draft: bool,
        prerelease: bool,
        make_latest: str,
    ) -> Release:
        raise NotImplementedError

    def list_assets(self, release_id: int) -> tuple[Asset, ...]:
        raise NotImplementedError

    def upload_asset(self, release_id: int, asset: PublishAsset) -> Asset:
        raise NotImplementedError

    def delete_asset(self, asset: Asset) -> None:
        raise NotImplementedError

    def download_asset(self, asset: Asset) -> bytes | None:
        """Return asset bytes for verification, or None when unavailable."""
        return None

    def log(self, message: str) -> None:
        print(message)


class NoNetworkAdapter(GitHubAdapter):
    """Dry-run adapter: reads are allowed, every mutation raises.

    Used by ``--dry-run`` so "performs no network calls" is enforced by the
    object graph rather than by a convention the reviewer has to trust.
    """

    def __init__(self, log: Callable[[str], None] = print) -> None:
        self._log = log
        self.attempted_mutations: list[str] = []

    def _forbidden(self, name: str) -> None:
        self.attempted_mutations.append(name)
        raise PublishAborted([f"dry-run: refusing to call mutating adapter method {name}"])

    def get_tag(self, tag: str) -> str | None:
        return None

    def get_release_by_tag(self, tag: str) -> Release | None:
        return None

    def list_assets(self, release_id: int) -> tuple[Asset, ...]:
        return ()

    def create_tag(self, *, tag: str, sha: str, message: str) -> None:
        self._forbidden("create_tag")

    def create_release(self, **_: Any) -> Release:
        self._forbidden("create_release")

    def update_release(self, release_id: int, **_: Any) -> Release:
        self._forbidden("update_release")

    def upload_asset(self, release_id: int, asset: PublishAsset) -> Asset:
        self._forbidden("upload_asset")

    def delete_asset(self, asset: Asset) -> None:
        self._forbidden("delete_asset")

    def download_asset(self, asset: Asset) -> bytes | None:
        return None

    def log(self, message: str) -> None:
        self._log(message)


# ---------------------------------------------------------------------------
# Local validation: build PublishInputs from one ZIP (0.9.12 "validate again")
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_payload_from_bytes(data: bytes, *, where: str = "ZIP") -> dict[str, bytes]:
    """Package-relative payload mapping of ZIP bytes (same rules as the file
    reader: single root, no symlinks)."""
    payload: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise PublishAborted(
                        [f"publish: {where} contains a symlink entry {info.filename!r}"]
                    )
                rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
                if not rel:
                    raise PublishAborted(
                        [f"publish: {where} has an entry outside the single root: "
                         f"{info.filename!r}"]
                    )
                payload[rel] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise PublishAborted([f"publish: {where} is not a readable ZIP: {exc}"]) from exc
    return payload


def read_zip_payload(zip_path: Path) -> tuple[bytes, dict[str, bytes]]:
    """Return (zip bytes, package-relative payload mapping) for one ZIP."""
    try:
        data = Path(zip_path).read_bytes()
    except OSError as exc:
        raise PublishAborted([f"publish: cannot read {zip_path}: {exc}"]) from exc
    return data, zip_payload_from_bytes(data, where=str(zip_path))


def verify_external_digest(zip_path: Path, zip_bytes: bytes) -> str:
    """Check ``<zip>.sha256`` against the actual ZIP bytes; return the digest."""
    digest = sha256_bytes(zip_bytes)
    sidecar = Path(str(zip_path) + ".sha256")
    if not sidecar.is_file():
        raise PublishAborted(
            [f"publish: {sidecar.name} is required beside the ZIP so the published "
             "digest is the one CI actually built"]
        )
    try:
        recorded = sidecar.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError) as exc:
        raise PublishAborted([f"publish: cannot parse {sidecar}: {exc}"]) from exc
    if recorded != digest:
        raise PublishAborted(
            [f"publish: {sidecar.name} records {recorded} but {zip_path.name} is {digest}"]
        )
    return digest


def check_manifest_identity(manifest: dict[str, Any], *, full_sha: str) -> list[str]:
    """The ZIP must be exactly the main build this publish invocation claims."""
    errors: list[str] = []
    errors.extend(contract.validate_manifest(manifest))
    source = manifest.get("source") or {}
    if source.get("kind") != "main":
        errors.append(f"publish: manifest source.kind {source.get('kind')!r} != 'main' "
                      "(only main builds are publishable)")
    if source.get("sha") != full_sha:
        errors.append(f"publish: manifest source.sha {source.get('sha')!r} != "
                      f"expected main SHA {full_sha!r}")
    want_build_id = f"main-{short_sha(full_sha)}"
    if manifest.get("build_id") != want_build_id:
        errors.append(f"publish: manifest build_id {manifest.get('build_id')!r} != "
                      f"{want_build_id!r}")
    want_tag = derive_tag("main", full_sha)
    if manifest.get("tag") != want_tag:
        errors.append(f"publish: manifest tag {manifest.get('tag')!r} != {want_tag!r}")
    if manifest.get("release_channel") != contract.RELEASE_CHANNEL:
        errors.append(f"publish: manifest release_channel "
                      f"{manifest.get('release_channel')!r} is not the prototype channel; "
                      "promotion is a separate gated decision")
    for field_name in ("hardware_verified", "recording_available", "device_ota_available"):
        if manifest.get(field_name) is not False:
            errors.append(f"publish: manifest {field_name} must be false for a prototype "
                          "bootstrap release (CI-09)")
    if manifest.get("ci") is None:
        errors.append("publish: manifest ci is null; a publishable main build carries "
                      "run_id/attempt from the workflow that built it")
    return errors


def release_body(manifest: dict[str, Any], notes_text: str) -> str:
    """Deterministic Release body: identity block + packaged notes."""
    source = manifest["source"]
    ci = manifest.get("ci") or {}
    zip_name = f"{package_root_name(manifest['build_id'])}.zip"
    lines = [
        f"{manifest['product']} {manifest['firmware_version']} firmware \u2014 main "
        f"{source['sha']}",
        "",
        f"- Tag: `{manifest['tag']}` (created at the full tested main SHA)",
        f"- Build ID: `{manifest['build_id']}`",
        f"- Source SHA: `{source['sha']}`",
        f"- Environment: `{manifest['environment']}` / board `{manifest['board']}` / "
        f"target `{manifest['target']}`",
        f"- Run: {ci.get('run_id')} attempt {ci.get('attempt')}",
        f"- Toolchain: PlatformIO Core {manifest['toolchain']['platformio_core']}, "
        f"{manifest['toolchain']['platform']}, ESP-IDF "
        f"{manifest['toolchain']['idf_version']}, esptool "
        f"{manifest['toolchain']['esptool_version']}",
        "",
        "**Prototype / build-host evidence only.** This bootstrap release is",
        f"`release_channel: {manifest['release_channel']}`,",
        f"`hardware_verified: {str(manifest['hardware_verified']).lower()}`,",
        f"`recording_available: {str(manifest['recording_available']).lower()}`,",
        f"`device_ota_available: {str(manifest['device_ota_available']).lower()}`.",
        "It does not record, offers no device OTA, and has no physical-device",
        "verification evidence. Install it only on a Seeed Studio XIAO ESP32S3",
        "Sense development board with the battery pack disconnected.",
        "",
        "## Assets",
        "",
        f"- `{zip_name}` \u2014 the complete installation bundle (single root directory)",
        f"- `{zip_name}.sha256` \u2014 external SHA-256 of the bundle",
        "- `INSTALL.md` \u2014 the prebuilt installation guide (also inside the ZIP)",
        "- `RELEASE_NOTES.md`, `THIRD_PARTY_NOTICES.md`, `manifest.json`",
        "",
        "Verify the bundle before running anything:",
        "",
        "```sh",
        "shasum -a 256 -c " + f"{zip_name}.sha256",
        "```",
        "",
        "Checksums detect corruption; authenticity still depends on downloading",
        "this release from the canonical repository.",
        "",
        "## Release notes",
        "",
        notes_text.rstrip("\n"),
        "",
    ]
    return "\n".join(lines)


def load_publish_inputs(
    zip_path: Path,
    *,
    expected_sha: str,
    run_installer_check: bool = False,
    verify_package: bool = True,
) -> PublishInputs:
    """Validate the ZIP offline and derive the full publish request.

    Every failure is raised before any adapter is constructed, so a corrupt or
    mis-identified build cannot reach GitHub (CI-07).
    """
    errors = contract.validate_source_sha(expected_sha, where="publish.expected_sha")
    if errors:
        raise PublishAborted(errors)
    zip_bytes, payload = read_zip_payload(zip_path)
    zip_sha256 = verify_external_digest(zip_path, zip_bytes)
    if verify_package:
        failures = validate_package_bytes(
            zip_bytes, expected_zip_sha256=zip_sha256,
            run_installer_check=run_installer_check,
        )
        if failures:
            raise PublishAborted([f"publish: {f}" for f in failures])
    try:
        manifest = json.loads(payload[contract.MANIFEST_FILE].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishAborted([f"publish: cannot load {contract.MANIFEST_FILE}: {exc}"]) from exc

    errors = check_manifest_identity(manifest, full_sha=expected_sha)
    if errors:
        raise PublishAborted(errors)

    zip_name = f"{package_root_name(manifest['build_id'])}.zip"
    assets = [
        PublishAsset(name=zip_name, data=zip_bytes, content_type="application/zip"),
        PublishAsset(
            name=f"{zip_name}.sha256",
            data=f"{zip_sha256}  {zip_name}\n".encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        ),
    ]
    for name, content_type in (
        ("INSTALL.md", "text/plain; charset=utf-8"),
        ("RELEASE_NOTES.md", "text/plain; charset=utf-8"),
        ("THIRD_PARTY_NOTICES.md", "text/plain; charset=utf-8"),
        (contract.MANIFEST_FILE, "application/json"),
    ):
        try:
            data = payload[name]
        except KeyError:
            raise PublishAborted(
                [f"publish: {Path(zip_path).name} does not contain {name} required as a "
                 "Release asset"]
            ) from None
        assets.append(PublishAsset(name=name, data=data, content_type=content_type))

    notes_bytes = payload["RELEASE_NOTES.md"]
    try:
        notes_text = notes_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - packaging guarantees UTF-8
        raise PublishAborted([f"publish: RELEASE_NOTES.md is not UTF-8: {exc}"]) from exc

    return PublishInputs(
        full_sha=expected_sha,
        build_id=str(manifest["build_id"]),
        tag=str(manifest["tag"]),
        version=str(manifest["firmware_version"]),
        title=TITLE_TEMPLATE.format(version=manifest["firmware_version"],
                                   sha12=short_sha(expected_sha)),
        body=release_body(manifest, notes_text),
        zip_name=zip_name,
        zip_sha256=zip_sha256,
        manifest=manifest,
        assets=tuple(assets),
    )


# ---------------------------------------------------------------------------
# Publish guards and state machine
# ---------------------------------------------------------------------------


def check_publish_context(
    *,
    repo: str,
    ref: str,
    event_name: str,
    expected_repo: str = DEFAULT_REPO,
    expected_ref: str = EXPECTED_REF,
    expected_event: str = EXPECTED_EVENT,
) -> None:
    """Refuse to publish from anything but a push to canonical main (CI-T13)."""
    errors: list[str] = []
    if repo != expected_repo:
        errors.append(f"publish: repository {repo!r} is not the canonical {expected_repo!r}")
    if ref != expected_ref:
        errors.append(f"publish: ref {ref!r} is not {expected_ref!r}")
    if event_name != expected_event:
        errors.append(f"publish: event {event_name!r} is not {expected_event!r}")
    if errors:
        raise PublishConflict(errors)


def _tag_annotation_message(inputs: PublishInputs) -> str:
    ci = inputs.manifest.get("ci") or {}
    return "\n".join(
        (
            f"vdog firmware release {inputs.tag}",
            "",
            f"version: {inputs.version}",
            f"build_id: {inputs.build_id}",
            f"source_sha: {inputs.full_sha}",
            f"environment: {inputs.manifest['environment']}",
            f"release_channel: {inputs.manifest['release_channel']}",
            f"run_id: {ci.get('run_id')}",
            f"attempt: {ci.get('attempt')}",
            f"zip_sha256: {inputs.zip_sha256}",
            "",
            "Created by .github/workflows/firmware-main.yml after firmware-build,",
            "firmware-host-tests and firmware-package-tests all passed. The tag is",
            "immutable: a conflicting target is a hard failure, never a move.",
        )
    )


def ensure_tag(adapter: GitHubAdapter, inputs: PublishInputs,
               report: PublishReport) -> str:
    """Create or reuse the immutable tag and verify its peeled target."""
    existing = adapter.get_tag(inputs.tag)
    if existing is not None:
        if existing != inputs.full_sha:
            raise PublishConflict(
                [f"publish: tag {inputs.tag} already resolves to {existing}, not the "
                 f"tested main SHA {inputs.full_sha}. The tag is immutable: refusing to "
                 "force, move or delete it. Inspect both revisions and repair manually."]
            )
        report.tag_action = "reused"
        report.actions.append(f"tag {inputs.tag} already at {existing}; reused")
        return existing

    adapter.create_tag(tag=inputs.tag, sha=inputs.full_sha,
                       message=_tag_annotation_message(inputs))
    report.tag_action = "created"
    report.actions.append(f"tag {inputs.tag} created at {inputs.full_sha}")
    peeled = adapter.get_tag(inputs.tag)
    if peeled != inputs.full_sha:
        raise PublishConflict(
            [f"publish: tag {inputs.tag} peeled to {peeled!r} after creation instead of "
             f"{inputs.full_sha!r}; refusing to publish a release at an unverified target"]
        )
    report.actions.append(f"tag {inputs.tag} peeled target verified as {peeled}")
    return peeled


def _identity_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    node = {key: manifest.get(key) for key in PUBLISHED_MANIFEST_IDENTITY_FIELDS}
    source = manifest.get("source") or {}
    node["source"] = {key: source.get(key) for key in PUBLISHED_SOURCE_IDENTITY_FIELDS}
    node["images"] = [
        {key: image.get(key) for key in ("role", "file", "offset", "size")}
        for image in manifest.get("images", [])
    ]
    return node


#: One canonical ``shasum -a 256`` checksum line: 64 hex digest, exactly two
#: spaces, then a bare file name (no path separators, no binary-mode ``*``).
CHECKSUM_LINE_PATTERN = re.compile(r"([0-9a-fA-F]{64})  ([^ \t/\\]+)")


def parse_checksum_file(text: str, *, expected_name: str) -> str:
    """Return the digest from a canonical ``shasum -a 256`` checksum file.

    A published ``<zip>.sha256`` must be exactly the one line that
    ``shasum -a 256`` writes and ``shasum -a 256 -c`` verifies (the very
    command this tool's Release body and the installation guide tell users
    to run)::

        <64-hex digest><two spaces><expected_name>

    A bare digest with no file name, a name that is not exactly
    *expected_name*, a name containing a path separator, the GNU binary-mode
    ``*`` marker, a single-space separator, or extra or missing lines are all
    rejected with ``ValueError``: the published digest is only trustworthy
    when the checksum tool the release itself documents can verify it.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the single terminating newline shasum itself writes
    if len(lines) != 1:
        raise ValueError(f"expected exactly one checksum line, found {len(lines)}")
    line = lines[0]
    match = CHECKSUM_LINE_PATTERN.fullmatch(line)
    if match is None:
        raise ValueError(
            f"{line[:72]!r} is not a canonical '<sha256>  <name>' checksum line "
            "(64 hex digest, exactly two spaces, bare file name)"
        )
    digest, name = match.groups()
    if name != expected_name:
        raise ValueError(
            f"the checksum line names {name!r}, not the release file "
            f"{expected_name!r}"
        )
    return digest.lower()


def _verify_published_zip(
    adapter: GitHubAdapter,
    release: Release,
    inputs: PublishInputs,
    report: PublishReport,
    errors: list[str],
    published_manifest_bytes: bytes | None,
) -> None:
    """P1-3: a reused published ZIP must VERIFY before reuse is reported.

    Before ``publish()`` may report ``reused-published`` it downloads the
    existing ZIP and its detached ``.sha256`` sidecar from the release and
    checks, in order: (1) the sidecar is the canonical one-line
    ``shasum -a 256`` checksum file naming exactly the release ZIP, and the
    ZIP bytes hash to the digest it records; (2) the ZIP is internally
    consistent (manifest digests, SHA256SUMS, images, headers) via the same
    validator CI runs; (3) the manifest EMBEDDED in the ZIP carries this
    build's verified release identity; and (4) the standalone published
    manifest.json — downloaded exactly once by the caller and passed in as
    *published_manifest_bytes* — matches the embedded manifest byte-for-byte.
    A ZIP or manifest that cannot be downloaded — i.e. cannot be verified —
    is an error, never a warning: reuse is reported only for a ZIP that
    actually passed every check. (A byte-different digest vs *this rebuild*
    stays a warning: identical source may legitimately rebuild
    byte-differently.)
    """
    assets = {asset.name: asset for asset in adapter.list_assets(release.id)}
    zip_asset = assets.get(inputs.zip_name)
    sidecar_asset = assets.get(f"{inputs.zip_name}.sha256")
    if zip_asset is None or sidecar_asset is None:
        errors.append(
            f"publish: cannot verify the published ZIP for reuse: "
            f"{inputs.zip_name} or its .sha256 sidecar is not on release "
            f"{release.id} (the asset-set check above records the mismatch)"
        )
        return
    zip_bytes = adapter.download_asset(zip_asset)
    if zip_bytes is None:
        errors.append(
            f"publish: published {inputs.zip_name} could not be downloaded; an "
            "unverified ZIP is never reported as reused — refusing "
            "reused-published for this release"
        )
        return
    sidecar_text = adapter.download_asset(sidecar_asset)
    if sidecar_text is None:
        errors.append(
            f"publish: published {inputs.zip_name}.sha256 could not be "
            "downloaded; reuse requires the detached digest to be verified"
        )
        return
    try:
        recorded = parse_checksum_file(
            sidecar_text.decode("utf-8"), expected_name=inputs.zip_name
        )
    except (UnicodeDecodeError, ValueError) as exc:
        errors.append(
            f"publish: published {inputs.zip_name}.sha256 is not a canonical "
            f"shasum -a 256 checksum file for {inputs.zip_name}: {exc}; reuse "
            "requires the exact '<sha256>  <file>' line that "
            f"'shasum -a 256 -c {inputs.zip_name}.sha256' verifies — reuse refused"
        )
        return
    digest = sha256_bytes(zip_bytes)
    if recorded != digest:
        errors.append(
            f"publish: published {inputs.zip_name} hashes to {digest} but its "
            f"published sidecar records {recorded}; the existing ZIP does not "
            "match its detached digest (tampered or corrupted) — reuse refused"
        )
    if digest != inputs.zip_sha256:
        report.warnings.append(
            f"published {inputs.zip_name} digest {digest[:12]}… differs from "
            f"this rebuild's {inputs.zip_sha256[:12]}…; identical source can "
            "legitimately rebuild byte-differently, so this is reported and "
            "never overwritten"
        )
    failures = validate_package_bytes(
        zip_bytes, expected_zip_sha256=recorded, run_installer_check=False
    )
    if failures:
        errors.extend(
            f"publish: published {inputs.zip_name} fails package validation "
            f"for reuse: {failure}"
            for failure in failures
        )
        return
    try:
        payload = zip_payload_from_bytes(
            zip_bytes, where=f"published {inputs.zip_name}"
        )
        embedded = json.loads(payload[contract.MANIFEST_FILE].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, PublishAborted) as exc:
        errors.append(
            f"publish: the manifest embedded in the published ZIP is "
            f"unreadable: {exc}; reuse refused"
        )
        return
    want = _identity_projection(inputs.manifest)
    got = _identity_projection(embedded)
    if want != got:
        differing = sorted(k for k in want if want.get(k) != got.get(k))
        errors.append(
            "publish: the manifest embedded in the published ZIP disagrees "
            f"on {differing} with the verified release identity; the ZIP does "
            "not contain the build its metadata claims — reuse refused"
        )
    embedded_manifest_bytes = payload[contract.MANIFEST_FILE]
    if published_manifest_bytes is None:
        errors.append(
            f"publish: the standalone published {contract.MANIFEST_FILE} is not "
            "downloadable from this release; reuse requires its bytes to be "
            "compared against the manifest embedded in the ZIP — an "
            "unverifiable manifest is never reported as reused"
        )
    elif published_manifest_bytes != embedded_manifest_bytes:
        errors.append(
            "publish: the standalone published manifest.json differs from the "
            "manifest embedded in the published ZIP; a swapped asset set is "
            "never reported as reused"
        )


def _verify_published_identity(
    adapter: GitHubAdapter,
    release: Release,
    inputs: PublishInputs,
    report: PublishReport,
) -> None:
    """A published release must carry the exact tested identity, or fail loudly.

    The standalone ``manifest.json`` asset is downloaded exactly ONCE here;
    its bytes are reused both for the manifest-identity check below and for
    the byte-for-byte comparison against the ZIP's embedded manifest in
    :func:`_verify_published_zip`. An undownloadable manifest is a hard
    failure recorded there, never a warning that skips the comparison.
    """
    errors: list[str] = []
    if release.tag_name != inputs.tag:
        errors.append(f"publish: published release targets tag {release.tag_name!r}, "
                      f"expected {inputs.tag!r}")
    if release.title != inputs.title:
        errors.append(f"publish: published release title {release.title!r} != "
                      f"{inputs.title!r}")
    if not release.prerelease:
        errors.append("publish: published release is not marked prerelease; prototype "
                      "bootstrap releases must be pre-releases (CI-09)")
    if release.make_latest != RELEASE_MAKE_LATEST:
        errors.append(f"publish: published release make_latest "
                      f"{release.make_latest!r} != {RELEASE_MAKE_LATEST!r}")

    existing_names = sorted(asset.name for asset in adapter.list_assets(release.id))
    if existing_names != sorted(inputs.asset_names):
        errors.append(
            f"publish: published release asset set {existing_names} != the validated "
            f"set {sorted(inputs.asset_names)}; a published release is never repaired "
            "in place"
        )

    published_manifest_bytes: bytes | None = None
    published_manifest = next(
        (asset for asset in adapter.list_assets(release.id)
         if asset.name == contract.MANIFEST_FILE),
        None,
    )
    if published_manifest is not None:
        published_manifest_bytes = adapter.download_asset(published_manifest)
        if published_manifest_bytes is not None:
            try:
                published_doc = json.loads(published_manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"publish: published manifest.json is unreadable: {exc}")
            else:
                want = _identity_projection(inputs.manifest)
                got = _identity_projection(published_doc)
                if want != got:
                    differing = sorted(k for k in want if want.get(k) != got.get(k))
                    errors.append(
                        "publish: the already published manifest disagrees on "
                        f"{differing}; refusing to treat it as this build "
                        "(never mixing builds)"
                    )
                want_hashes = {i["role"]: i["sha256"]
                               for i in inputs.manifest.get("images", [])}
                got_hashes = {i["role"]: i["sha256"]
                              for i in published_doc.get("images", [])}
                if want_hashes != got_hashes:
                    changed = sorted(
                        role for role in set(want_hashes) | set(got_hashes)
                        if want_hashes.get(role) != got_hashes.get(role)
                    )
                    report.warnings.append(
                        "published image digests differ from this rebuild for roles "
                        f"{changed}; identical source can legitimately rebuild "
                        "byte-differently, so this is reported and never overwritten"
                    )

    _verify_published_zip(adapter, release, inputs, report, errors,
                          published_manifest_bytes)

    if errors:
        raise PublishConflict(errors)


def _replace_asset_set(
    adapter: GitHubAdapter,
    release: Release,
    inputs: PublishInputs,
    report: PublishReport,
) -> None:
    """Replace the draft's entire asset set with one validated attempt.

    Delete-all first, then upload-all, then verify: an interruption leaves a
    draft with an incomplete set and a raised error, never a published
    release and never a mix of two builds.
    """
    for asset in adapter.list_assets(release.id):
        adapter.delete_asset(asset)
        report.actions.append(f"asset {asset.name} (id {asset.id}) removed from draft")
    uploaded: list[str] = []
    try:
        for asset in inputs.assets:
            adapter.upload_asset(release.id, asset)
            uploaded.append(asset.name)
            report.actions.append(
                f"asset {asset.name} uploaded ({asset.size} bytes, "
                f"sha256 {asset.sha256[:12]}\u2026)"
            )
    except Exception as exc:  # noqa: BLE001 - any transport failure is a repairable stop
        raise PublishAborted(
            [f"publish: asset upload interrupted after {len(uploaded)}/"
             f"{len(inputs.assets)} assets ({type(exc).__name__}: {exc}).",
             f"The draft for {inputs.tag} is left unpublished with "
             f"{uploaded or 'no'} assets: this is an explicit failed, repairable "
             "state. Rerun the same main commit to replace the whole asset set.",
             "Already uploaded in this attempt: " + (", ".join(uploaded) or "none"),
             "Still missing: " + ", ".join(
                 name for name in inputs.asset_names if name not in uploaded
             )]
        ) from exc

    final_names = sorted(asset.name for asset in adapter.list_assets(release.id))
    if final_names != sorted(inputs.asset_names):
        raise PublishAborted(
            [f"publish: after upload the asset set {final_names} != the validated set "
             f"{sorted(inputs.asset_names)}; not publishing"]
        )


def publish(
    adapter: GitHubAdapter,
    inputs: PublishInputs,
    *,
    dry_run: bool = False,
) -> PublishReport:
    """Run the tag/release state machine against ``adapter``.

    Returns a :class:`PublishReport`. Conflicts raise :class:`PublishConflict`
    and interrupted/invalid states raise :class:`PublishAborted`; both leave
    the remote in a repairable state and never rewrite history.
    """
    if dry_run and not isinstance(adapter, NoNetworkAdapter):
        # A dry run must be structurally incapable of mutating: refuse an
        # adapter that could, rather than trusting the caller's intent.
        raise PublishAborted(
            [f"dry-run: refusing to run against {type(adapter).__name__}; the dry-run "
             "path requires the mutating-free NoNetworkAdapter"]
        )
    if dry_run and isinstance(adapter, NoNetworkAdapter):
        report = PublishReport(
            decision="dry-run",
            tag_action="would create" if adapter.get_tag(inputs.tag) is None else "would reuse",
            release_action="would create draft, upload assets and publish",
            release_id=None,
            tag=inputs.tag,
            target_sha=inputs.full_sha,
            title=inputs.title,
            asset_names=inputs.asset_names,
            actions=[
                f"would create annotated tag {inputs.tag} at {inputs.full_sha} "
                "(none exists yet)",
                f"would create a draft release against {inputs.tag} "
                "(target_commitish = the verified full SHA, never a branch)",
                f"would upload {len(inputs.assets)} validated assets: "
                + ", ".join(inputs.asset_names),
                "would then mark the release published "
                "(prerelease=true, make_latest=false)",
                "no network calls performed (dry run)",
            ],
        )
        adapter.log("dry-run: no network calls performed")
        return report

    report = PublishReport(
        decision="unknown",
        tag_action="none",
        release_action="none",
        release_id=None,
        tag=inputs.tag,
        target_sha=inputs.full_sha,
        title=inputs.title,
        asset_names=inputs.asset_names,
    )
    ensure_tag(adapter, inputs, report)
    release = adapter.get_release_by_tag(inputs.tag)

    if release is not None and not release.draft:
        _verify_published_identity(adapter, release, inputs, report)
        report.decision = "reused-published"
        report.release_id = release.id
        report.release_action = "reused (published releases are never overwritten)"
        report.actions.append(
            f"release {release.id} is already published for {inputs.tag}; reused"
        )
        return report

    if release is None:
        release = adapter.create_release(
            tag=inputs.tag,
            target_sha=inputs.full_sha,
            title=inputs.title,
            body=inputs.body,
            draft=True,
            prerelease=RELEASE_PRERELEASE,
            make_latest=RELEASE_MAKE_LATEST,
        )
        report.release_id = release.id
        report.release_action = "created draft"
        report.actions.append(
            f"draft release {release.id} created against verified tag {inputs.tag}"
        )
    else:
        errors: list[str] = []
        if release.tag_name != inputs.tag:
            errors.append(f"publish: draft release {release.id} targets tag "
                          f"{release.tag_name!r}, expected {inputs.tag!r}")
        if release.target_commitish not in (None, "", inputs.tag, inputs.full_sha):
            # Informational only. The tag this draft is bound to was just
            # peeled-verified against the tested SHA, the binding itself is
            # checked above, and this tool can neither move the tag nor retarget
            # the release; GitHub also normalises this field (an existing tag is
            # frequently reported as the default branch). Treating it as fatal
            # would strand a repairable draft that 0.9.13 requires us to finish.
            report.warnings.append(
                f"publish: draft release {release.id} reports "
                f"target_commitish={release.target_commitish!r} rather than the verified "
                f"tag or {inputs.full_sha!r}; the bound tag was verified against the "
                "tested SHA, so the release is repaired against that tag"
            )
        if errors:
            raise PublishConflict(errors)
        report.release_id = release.id
        report.release_action = "repaired draft"
        report.actions.append(
            f"draft release {release.id} for {inputs.tag} is unpublished; replacing its "
            "entire asset set with this validated attempt"
        )

    _replace_asset_set(adapter, release, inputs, report)

    published = adapter.update_release(
        release.id,
        title=inputs.title,
        body=inputs.body,
        draft=False,
        prerelease=RELEASE_PRERELEASE,
        make_latest=RELEASE_MAKE_LATEST,
    )
    if published.draft:
        raise PublishAborted(
            [f"publish: release {release.id} is still a draft after the publish request; "
             "treating this as a failed release"]
        )
    report.release_id = published.id
    report.decision = ("published-new" if report.release_action == "created draft"
                       else "published-repaired-draft")
    report.actions.append(
        f"release {published.id} published (prerelease={published.prerelease}, "
        f"make_latest={published.make_latest!r})"
    )
    return report


def publish_main(
    zip_path: Path,
    *,
    expected_sha: str,
    repo: str,
    ref: str,
    event_name: str,
    expected_repo: str = DEFAULT_REPO,
    adapter: GitHubAdapter | None = None,
    dry_run: bool = False,
    run_installer_check: bool = False,
    verify_package: bool = True,
) -> PublishReport:
    """Validate locally, then publish. The adapter is built only after the
    local validation and context guard pass, so nothing talks to GitHub for a
    package that cannot be published."""
    check_publish_context(repo=repo, ref=ref, event_name=event_name,
                          expected_repo=expected_repo)
    inputs = load_publish_inputs(
        zip_path,
        expected_sha=expected_sha,
        run_installer_check=run_installer_check,
        verify_package=verify_package,
    )
    if adapter is None:
        if dry_run:
            adapter = NoNetworkAdapter()
        else:
            adapter = RestGitHubAdapter(repo=repo)
    return publish(adapter, inputs, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Real adapter: GitHub REST over urllib (stdlib only, no ambient CLI)
# ---------------------------------------------------------------------------


class GitHubApiError(PublishAborted):
    """A GitHub REST call failed.

    ``status`` carries the numeric HTTP status when the API answered, so
    "this object does not exist yet" is decided by the status code and never by
    matching text in a response body.
    """

    def __init__(self, errors: list[str], *, status: int | None = None) -> None:
        super().__init__(errors)
        self.status = status


def _is_not_found(exc: BaseException) -> bool:
    """True only when GitHub itself answered 404 for this request."""
    return getattr(exc, "status", None) == 404


def next_page_url(link_header: str | None) -> str | None:
    """Parse the RFC 5988 ``Link`` header and return the ``rel="next"`` URL."""
    if not link_header:
        return None
    for part in link_header.split(","):
        bits = [bit.strip() for bit in part.split(";")]
        if not bits[0].startswith("<") or ">" not in bits[0]:
            continue
        url = bits[0][1:bits[0].index(">")]
        for parameter in bits[1:]:
            if parameter.strip().lower() in ('rel="next"', "rel=next"):
                return url or None
    return None


class _TokenPinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never let the workflow token follow a redirect to another host.

    ``urllib`` re-uses the original headers on a redirect, which would re-send
    ``Authorization`` to whatever host the redirect names. Asset download URLs
    legitimately leave ``api.github.com`` (they point at GitHub's blob storage),
    so redirects still work — the credential is simply dropped when the host
    changes.
    """

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: Any,
        headers: Any,
        newurl: str,
    ) -> Any:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        origin = urllib.parse.urlsplit(req.full_url).netloc
        target = urllib.parse.urlsplit(newurl).netloc
        if target != origin and redirected.has_header("Authorization"):
            redirected.remove_header("Authorization")
        return redirected


class RestGitHubAdapter(GitHubAdapter):
    """GitHub REST adapter for the trusted publish job.

    Only the endpoints ``GitHubAdapter`` exposes exist here; tag update or
    delete operations are intentionally absent. Authenticated with the
    workflow's ``GITHUB_TOKEN`` (``contents: write`` on the publish job only).
    A token/ruleset rejection is reported, never bypassed.
    """

    def __init__(
        self,
        *,
        repo: str,
        token: str | None = None,
        api_url: str | None = None,
        upload_url: str | None = None,
        timeout: int = DEFAULT_API_TIMEOUT_SECONDS,
        log: Callable[[str], None] = print,
    ) -> None:
        self.repo = repo
        resolved_token = token if token is not None else (
            os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        )
        if not resolved_token:
            raise PublishAborted(
                ["publish: no GITHUB_TOKEN/GH_TOKEN available; the publish job must "
                 "grant contents:write to this job only"]
            )
        self._token = resolved_token
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.upload_url = (upload_url or os.environ.get("GITHUB_UPLOAD_URL")
                           or DEFAULT_UPLOAD_URL).rstrip("/")
        self.timeout = timeout
        self._log = log
        # One opener for the run: redirects keep working (asset downloads need
        # them) but the token never crosses a host boundary.
        self._opener = urllib.request.build_opener(_TokenPinnedRedirectHandler())

    # -- transport ---------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        payload: Any = None,
        raw: bytes | None = None,
        content_type: str = "application/json",
        accept: str = "application/vnd.github+json",
    ) -> tuple[int, bytes, dict[str, str]]:
        body: bytes | None = None
        if raw is not None:
            body = raw
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", accept)
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "vdog-firmware-publish")
        if body is not None:
            request.add_header("Content-Type", content_type)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.status, response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise GitHubApiError(
                [f"publish: GitHub {method} {url} failed with {exc.code}: {detail}"],
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubApiError(
                [f"publish: GitHub {method} {url} could not reach the API: {exc.reason}"]
            ) from exc

    def _json(self, method: str, url: str, *, payload: Any = None) -> Any:
        status, data, _headers = self._request(method, url, payload=payload)
        if not data.strip():
            return {}
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubApiError(
                [f"publish: GitHub {method} {url} returned unparseable JSON "
                 f"(status {status}): {data[:200]!r}"]
            ) from exc

    def _json_all_pages(self, url: str, *, max_pages: int = 50) -> list[Any]:
        """Collect every item of a paginated list endpoint.

        ``list_assets`` must see the *whole* set: a half-enumerated draft would
        leave stale assets behind, and the pre-publish completeness check would
        then reject a repair that actually succeeded.
        """
        items: list[Any] = []
        page_url: str | None = url
        pages = 0
        while page_url is not None:
            pages += 1
            if pages > max_pages:
                raise GitHubApiError(
                    [f"publish: {url} did not finish paginating within {max_pages} pages; "
                     "refusing to work from a partial asset list"]
                )
            status, data, headers = self._request("GET", page_url)
            try:
                doc = json.loads(data.decode("utf-8") or "[]")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GitHubApiError(
                    [f"publish: GitHub GET {page_url} returned unparseable JSON "
                     f"(status {status}): {data[:200]!r}"]
                ) from exc
            if isinstance(doc, dict):          # tolerate an enveloped response
                doc = doc.get("assets") or doc.get("items") or []
            items.extend(doc)
            page_url = next_page_url(headers.get("Link") or headers.get("link"))
        return items

    def _assets_of(self, doc: dict[str, Any]) -> tuple[Asset, ...]:
        return tuple(
            Asset(
                id=int(item["id"]),
                name=str(item["name"]),
                size=int(item.get("size", 0)),
                download_url=item.get("browser_download_url") or item.get("url"),
            )
            for item in doc.get("assets", [])
        )

    # -- GitHubAdapter surface --------------------------------------------
    def log(self, message: str) -> None:
        self._log(message)

    def get_tag(self, tag: str) -> str | None:
        url = f"{self.api_url}/repos/{self.repo}/git/ref/tags/{urllib.parse.quote(tag)}"
        try:
            doc = self._json("GET", url)
        except GitHubApiError as exc:
            if _is_not_found(exc):
                return None
            raise
        obj = doc.get("object") or {}
        sha = obj.get("sha")
        if not sha:
            raise GitHubApiError([f"publish: unexpected ref response for {tag}: {doc!r}"])
        if obj.get("type") == "tag":  # annotated tag: peel to the commit
            tag_doc = self._json("GET", f"{self.api_url}/repos/{self.repo}/git/tags/{sha}")
            sha = (tag_doc.get("object") or {}).get("sha")
        return sha

    def create_tag(self, *, tag: str, sha: str, message: str) -> None:
        tag_doc = self._json(
            "POST",
            f"{self.api_url}/repos/{self.repo}/git/tags",
            payload={
                "tag": tag,
                "message": message,
                "object": sha,
                "type": "commit",
                "tagger": {
                    "name": TAG_ANNOTATION_NAME,
                    "email": TAG_ANNOTATION_EMAIL,
                    "date": TAG_ANNOTATION_DATE,
                },
            },
        )
        tag_sha = tag_doc.get("sha")
        if not tag_sha:
            raise GitHubApiError([f"publish: created tag object has no sha: {tag_doc!r}"])
        self._json(
            "POST",
            f"{self.api_url}/repos/{self.repo}/git/refs",
            payload={"ref": f"refs/tags/{tag}", "sha": tag_sha},
        )

    def get_release_by_tag(self, tag: str) -> Release | None:
        url = (f"{self.api_url}/repos/{self.repo}/releases/tags/"
               f"{urllib.parse.quote(tag)}")
        try:
            doc = self._json("GET", url)
        except GitHubApiError as exc:
            if _is_not_found(exc):
                return None
            raise
        if not doc.get("id"):
            return None
        return self._release(doc)

    def _release(self, doc: dict[str, Any]) -> Release:
        return Release(
            id=int(doc["id"]),
            tag_name=str(doc.get("tag_name", "")),
            draft=bool(doc.get("draft", False)),
            prerelease=bool(doc.get("prerelease", False)),
            make_latest=str(doc.get("make_latest", RELEASE_MAKE_LATEST)),
            title=str(doc.get("name", "")),
            target_commitish=doc.get("target_commitish"),
            assets=self._assets_of(doc),
        )

    def create_release(
        self,
        *,
        tag: str,
        target_sha: str,
        title: str,
        body: str,
        draft: bool,
        prerelease: bool,
        make_latest: str,
    ) -> Release:
        doc = self._json(
            "POST",
            f"{self.api_url}/repos/{self.repo}/releases",
            payload={
                "tag_name": tag,
                # The tag already exists and is verified; pinning the full SHA
                # here means the target can never fall back to the default
                # branch even if the API resolved things differently.
                "target_commitish": target_sha,
                "name": title,
                "body": body,
                "draft": draft,
                "prerelease": prerelease,
                "make_latest": make_latest,
            },
        )
        if not doc.get("id"):
            raise GitHubApiError([f"publish: release creation returned no id: {doc!r}"])
        return self._release(doc)

    def update_release(
        self,
        release_id: int,
        *,
        title: str,
        body: str,
        draft: bool,
        prerelease: bool,
        make_latest: str,
    ) -> Release:
        doc = self._json(
            "PATCH",
            f"{self.api_url}/repos/{self.repo}/releases/{release_id}",
            payload={
                "name": title,
                "body": body,
                "draft": draft,
                "prerelease": prerelease,
                "make_latest": make_latest,
            },
        )
        return self._release(doc)

    def list_assets(self, release_id: int) -> tuple[Asset, ...]:
        docs = self._json_all_pages(
            f"{self.api_url}/repos/{self.repo}/releases/{release_id}/assets?per_page=100"
        )
        return tuple(
            Asset(id=int(item["id"]), name=str(item["name"]),
                  size=int(item.get("size", 0)),
                  download_url=item.get("browser_download_url") or item.get("url"))
            for item in docs
        )

    def upload_asset(self, release_id: int, asset: PublishAsset) -> Asset:
        query = urllib.parse.urlencode({"name": asset.name})
        url = (f"{self.upload_url}/repos/{self.repo}/releases/{release_id}/assets?{query}")
        _, data, _headers = self._request("POST", url, raw=asset.data,
                                          content_type=asset.content_type)
        try:
            doc = json.loads(data.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubApiError(
                [f"publish: asset upload for {asset.name} returned unparseable JSON"]
            ) from exc
        if not doc.get("id"):
            raise GitHubApiError(
                [f"publish: asset upload for {asset.name} returned no id: {doc!r}"]
            )
        return Asset(id=int(doc["id"]), name=str(doc.get("name", asset.name)),
                     size=int(doc.get("size", asset.size)),
                     download_url=doc.get("browser_download_url") or doc.get("url"))

    def delete_asset(self, asset: Asset) -> None:
        self._request(
            "DELETE", f"{self.api_url}/repos/{self.repo}/releases/assets/{asset.id}"
        )

    def download_asset(self, asset: Asset) -> bytes | None:
        url = asset.download_url
        if not url:
            return None
        if url.startswith("https://") is False:
            url = f"{self.api_url}{url}"
        try:
            _, data, _headers = self._request("GET", url, accept="application/octet-stream")
        except GitHubApiError as exc:
            self.log(f"warning: {exc}")
            return None
        return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.firmware.publish",
        description="Create/verify the immutable main tag and publish the complete "
                    "GitHub Release for one validated installation ZIP.",
    )
    parser.add_argument("--zip", dest="zip_path", type=Path, required=True,
                        help="installation ZIP (its .sha256 sidecar is required)")
    parser.add_argument("--expected-sha", required=True,
                        help="full 40-hex main SHA this build must be (github.sha)")
    parser.add_argument("--repo", default=os.environ.get("VDOG_PUBLISH_REPO", DEFAULT_REPO))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", EXPECTED_REF))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME",
                                                              EXPECTED_EVENT))
    parser.add_argument("--expected-repo", default=DEFAULT_REPO,
                        help="canonical repository allowed to publish")
    parser.add_argument("--dry-run", action="store_true",
                        help="perform no network calls and no mutation; print the plan")
    parser.add_argument("--skip-package-validation", action="store_true",
                        help="forensics only: skip the offline archive re-validation")
    parser.add_argument("--installer-check", action="store_true",
                        help="also run the packaged install.py check while re-validating")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    try:
        report = publish_main(
            args.zip_path,
            expected_sha=args.expected_sha,
            repo=args.repo,
            ref=args.ref,
            event_name=args.event_name,
            expected_repo=args.expected_repo,
            dry_run=args.dry_run,
            run_installer_check=args.installer_check,
            verify_package=not args.skip_package_validation,
        )
    except ContractError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 0
    print(f"publish: {report.decision}")
    print(f"  tag:   {report.tag} ({report.tag_action}) at {report.target_sha}")
    print(f"  title: {report.title}")
    print(f"  assets: {', '.join(report.asset_names)}")
    for action in report.actions:
        print(f"  - {action}")
    for warning in report.warnings:
        print(f"  ! {warning}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
