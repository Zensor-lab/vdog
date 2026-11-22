"""Spec-derived operation table for the two OpenAPI documents.

This table is the executable mirror of ``docs/specs/interfaces.md``: for every
operation it records the documented success statuses, the documented rejection
statuses and the stable ``error.code`` names the spec assigns to each. The
validator uses it twice:

* structurally, to require that each operation in the OpenAPI file declares at
  least these statuses and nothing outside the documented set; and
* semantically, to require that every error-response fixture uses a code the spec
  (or :data:`ILLUSTRATIVE_CODES`, documented in ``contracts/README.md``) allows for
  that status.

Keeping it separate from the YAML is deliberate: the YAML is the published
contract and this table is the independent checklist that keeps it honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Mapping

from .bounds import (
    MAX_UPLOAD_INIT_BODY_BYTES,
)

#: Codes named verbatim in ``docs/specs/interfaces.md``.
SPEC_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "STORAGE_FULL",
        "ALREADY_OWNED",
        "CURSOR_EXPIRED",
        "REVISION_CONFLICT",
        "LEASE_LIMIT",
        "STORAGE_PRESSURE",
        "LEASE_EXPIRED",
        "CLIP_GONE",
        "CONTENT_CHANGED",
        "PROTECTION_QUOTA",
        "CLIP_ID_COLLISION",
        "CLIP_PROTECTED",
    }
)

#: The spec assigns a status but no stable name for these generic rejections.
#: They are listed in ``contracts/README.md`` under "Illustrative choices"; the
#: ``code`` schema stays an open pattern so no consumer is forced to adopt them.
ILLUSTRATIVE_CODES: Final[frozenset[str]] = frozenset(
    {
        "MALFORMED_REQUEST",
        "UNAUTHENTICATED",
        "FORBIDDEN",
        "NOT_FOUND",
        "BOUND_EXCEEDED",
        "RANGE_INVALID",
        "INTEGRITY_FAILURE",
        "RATE_LIMITED",
        "UNAVAILABLE",
        "IDEMPOTENCY_CONFLICT",
        "OFFSET_CONFLICT",
        "EXPIRED",
    }
)

ALLOWED_ERROR_CODES: Final[frozenset[str]] = SPEC_ERROR_CODES | ILLUSTRATIVE_CODES


@dataclass(frozen=True)
class Operation:
    """One documented operation of one contract."""

    key: str
    contract: str
    operation_id: str
    method: str
    path: str
    request_schema: str | None = None
    response_schemas: Mapping[int, str | None] = field(default_factory=dict)
    success_statuses: tuple[int, ...] = ()
    error_codes: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    required_request_headers: tuple[str, ...] = ()
    required_response_headers: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    body_bound_bytes: int | None = None

    @property
    def documented_statuses(self) -> tuple[int, ...]:
        """Every status the spec assigns this operation, sorted."""
        return tuple(sorted(set(self.success_statuses) | set(self.error_codes)))

    def allowed_codes_for(self, status: int) -> frozenset[str]:
        """Codes the spec (or the documented illustrative set) allows for a status."""
        listed = self.error_codes.get(status, ())
        return frozenset(listed) | ILLUSTRATIVE_CODES


def _op(key: str, contract: str, operation_id: str, method: str, path: str, **kwargs: object) -> Operation:
    return Operation(key=key, contract=contract, operation_id=operation_id, method=method, path=path, **kwargs)  # type: ignore[arg-type]


DEVICE_OPERATIONS: Final[dict[str, Operation]] = {
    op.key: op
    for op in (
        _op(
            "device.pair",
            "device",
            "pair",
            "POST",
            "/pair",
            request_schema="PairRequest",
            response_schemas={201: "PairResponse"},
            success_statuses=(201,),
            error_codes={400: ("MALFORMED_REQUEST",), 409: ("ALREADY_OWNED",), 429: ("RATE_LIMITED",)},
        ),
        _op(
            "device.revoke_token",
            "device",
            "revokeToken",
            "POST",
            "/tokens/revoke",
            request_schema="RevokeTokenRequest",
            response_schemas={200: "RevokeTokenResponse"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 404: ("NOT_FOUND",)},
        ),
        _op(
            "device.get_capabilities",
            "device",
            "getCapabilities",
            "GET",
            "/capabilities",
            response_schemas={200: "CapabilitiesResponse"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",)},
        ),
        _op(
            "device.get_status",
            "device",
            "getStatus",
            "GET",
            "/status",
            response_schemas={200: "StatusResponse"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 503: ("UNAVAILABLE",)},
        ),
        _op(
            "device.get_settings",
            "device",
            "getSettings",
            "GET",
            "/settings",
            response_schemas={200: "SettingsResponse"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",)},
        ),
        _op(
            "device.put_settings",
            "device",
            "putSettings",
            "PUT",
            "/settings",
            request_schema="PutSettingsRequest",
            response_schemas={200: "PutSettingsResponse"},
            success_statuses=(200,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                409: ("REVISION_CONFLICT",),
            },
        ),
        _op(
            "device.post_time",
            "device",
            "postTime",
            "POST",
            "/time",
            request_schema="TimeRequest",
            response_schemas={200: "TimeResponse"},
            success_statuses=(200,),
            error_codes={400: ("MALFORMED_REQUEST",), 401: ("UNAUTHENTICATED",)},
        ),
        _op(
            "device.get_preview",
            "device",
            "getPreview",
            "GET",
            "/preview",
            response_schemas={200: None},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 503: ("UNAVAILABLE",)},
        ),
        _op(
            "device.list_clips",
            "device",
            "listClips",
            "GET",
            "/clips",
            response_schemas={200: "ClipsPage"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 409: ("CURSOR_EXPIRED",)},
        ),
        _op(
            "device.get_clip_manifest",
            "device",
            "getClipManifest",
            "GET",
            "/clips/{clip_id}/manifest",
            response_schemas={200: "Manifest"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 404: ("NOT_FOUND",), 410: ("CLIP_GONE",)},
        ),
        _op(
            "device.create_lease",
            "device",
            "createLease",
            "POST",
            "/clips/{clip_id}/leases",
            request_schema="VersionedRequest",
            response_schemas={201: "LeaseResponse"},
            success_statuses=(201,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                404: ("NOT_FOUND",),
                409: ("LEASE_LIMIT",),
                410: ("CLIP_GONE",),
            },
        ),
        _op(
            "device.renew_lease",
            "device",
            "renewLease",
            "PUT",
            "/leases/{lease_id}",
            request_schema="VersionedRequest",
            response_schemas={200: "LeaseResponse"},
            success_statuses=(200,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                404: ("NOT_FOUND",),
                409: ("STORAGE_PRESSURE", "LEASE_EXPIRED"),
            },
        ),
        _op(
            "device.delete_lease",
            "device",
            "deleteLease",
            "DELETE",
            "/leases/{lease_id}",
            success_statuses=(204,),
            error_codes={401: ("UNAUTHENTICATED",)},
        ),
        _op(
            "device.get_clip_file",
            "device",
            "getClipFile",
            "GET",
            "/clips/{clip_id}/files/{name}",
            response_schemas={200: None, 206: None},
            success_statuses=(200, 206),
            # interfaces.md §4 assigns every range outcome of this endpoint to 416 —
            # the forms the contract rejects as well as the ones a given file cannot
            # satisfy — while §1 keeps generic 400 for request-level defects. A
            # (400, RANGE_INVALID) pair here would be contract surface the validator
            # itself refuses to certify: `_rule_range` makes a 200/206 answer to a
            # rejected range form a violation and a 416 the only range answer, so no
            # conformant vector could ever demonstrate it. ``backend.get_clip_file``
            # documents no 400 row at all, so retiring it also removes the device's
            # asymmetry against its own mirror rather than creating one.
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                404: ("NOT_FOUND",),
                409: ("LEASE_EXPIRED",),
                410: ("CLIP_GONE",),
                412: ("CONTENT_CHANGED",),
                416: ("RANGE_INVALID",),
            },
            required_request_headers=("X-Clip-Lease",),
            required_response_headers={
                200: ("Accept-Ranges", "ETag", "Content-Length"),
                206: ("Accept-Ranges", "Content-Range", "ETag", "Content-Length"),
            },
        ),
        _op(
            "device.post_ota",
            "device",
            "postOta",
            "POST",
            "/ota",
            response_schemas={202: "OtaStageResponse"},
            success_statuses=(202,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                413: ("BOUND_EXCEEDED",),
                422: ("INTEGRITY_FAILURE",),
                # Staging needs room for a second inactive image, so this is where
                # the spec's own STORAGE_FULL example legitimately belongs.
                503: ("UNAVAILABLE", "STORAGE_FULL"),
            },
        ),
        _op(
            "device.create_event",
            "device",
            "createEvent",
            "POST",
            "/events",
            request_schema="DeviceEventRequest",
            response_schemas={201: "DeviceEventResponse"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                409: ("PROTECTION_QUOTA", "IDEMPOTENCY_CONFLICT"),
            },
        ),
        _op(
            "device.list_events",
            "device",
            "listEvents",
            "GET",
            "/events",
            response_schemas={200: "DeviceEventsPage"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 409: ("CURSOR_EXPIRED",)},
        ),
        _op(
            "device.delete_event",
            "device",
            "deleteEvent",
            "DELETE",
            "/events/{event_id}",
            success_statuses=(204,),
            error_codes={401: ("UNAUTHENTICATED",), 404: ("NOT_FOUND",)},
        ),
    )
}


BACKEND_OPERATIONS: Final[dict[str, Operation]] = {
    op.key: op
    for op in (
        _op(
            "backend.create_token",
            "backend",
            "createToken",
            "POST",
            "/tokens",
            request_schema="CreateTokenRequest",
            response_schemas={201: "CreateTokenResponse"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
            },
        ),
        _op(
            "backend.delete_token",
            "backend",
            "deleteToken",
            "DELETE",
            "/tokens/{id}",
            success_statuses=(204,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
            },
        ),
        _op(
            "backend.register_device",
            "backend",
            "registerDevice",
            "POST",
            "/devices",
            request_schema="RegisterDeviceRequest",
            response_schemas={201: "DeviceRecord"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                409: ("IDEMPOTENCY_CONFLICT",),
            },
        ),
        _op(
            "backend.list_devices",
            "backend",
            "listDevices",
            "GET",
            "/devices",
            response_schemas={200: "DevicesPage"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 409: ("CURSOR_EXPIRED",)},
        ),
        _op(
            "backend.list_clips",
            "backend",
            "listClips",
            "GET",
            "/clips",
            response_schemas={200: "BackendClipsPage"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 409: ("CURSOR_EXPIRED",)},
        ),
        _op(
            "backend.get_clip",
            "backend",
            "getClip",
            "GET",
            "/clips/{clip_id}",
            response_schemas={200: "StoredClip"},
            success_statuses=(200,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                410: ("CLIP_GONE",),
            },
        ),
        _op(
            "backend.delete_clip",
            "backend",
            "deleteClip",
            "DELETE",
            "/clips/{clip_id}",
            response_schemas={202: "DeletingResponse"},
            success_statuses=(202,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                409: ("CLIP_PROTECTED",),
                410: ("CLIP_GONE",),
            },
        ),
        _op(
            "backend.get_clip_file",
            "backend",
            "getClipFile",
            "GET",
            "/clips/{clip_id}/files/{name}",
            response_schemas={200: None, 206: None},
            success_statuses=(200, 206),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                410: ("CLIP_GONE",),
                412: ("CONTENT_CHANGED",),
                416: ("RANGE_INVALID",),
            },
            required_response_headers={
                200: ("Accept-Ranges", "ETag", "Content-Length"),
                206: ("Accept-Ranges", "Content-Range", "ETag", "Content-Length"),
            },
        ),
        _op(
            "backend.get_derivative_file",
            "backend",
            "getDerivativeFile",
            "GET",
            "/derivatives/{id}/file",
            response_schemas={200: None, 206: None},
            success_statuses=(200, 206),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                412: ("CONTENT_CHANGED",),
                416: ("RANGE_INVALID",),
            },
            required_response_headers={
                200: ("Accept-Ranges", "ETag", "Content-Length"),
                206: ("Accept-Ranges", "Content-Range", "ETag", "Content-Length"),
            },
        ),
        _op(
            "backend.create_upload",
            "backend",
            "createUpload",
            "POST",
            "/uploads",
            request_schema="CreateUploadRequest",
            response_schemas={201: "UploadCreated"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                409: ("IDEMPOTENCY_CONFLICT",),
                413: ("BOUND_EXCEEDED",),
                422: ("INTEGRITY_FAILURE",),
            },
            required_request_headers=("Idempotency-Key",),
            body_bound_bytes=MAX_UPLOAD_INIT_BODY_BYTES,
        ),
        _op(
            "backend.head_upload_file",
            "backend",
            "headUploadFile",
            "HEAD",
            "/uploads/{id}/files/{name}",
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 404: ("NOT_FOUND",), 410: ("EXPIRED",)},
            required_response_headers={200: ("Upload-Offset", "Upload-Length")},
        ),
        _op(
            "backend.patch_upload_file",
            "backend",
            "patchUploadFile",
            "PATCH",
            "/uploads/{id}/files/{name}",
            success_statuses=(204,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                409: ("OFFSET_CONFLICT",),
                413: ("BOUND_EXCEEDED",),
                422: ("INTEGRITY_FAILURE",),
            },
            required_request_headers=("Upload-Offset", "Upload-Checksum", "Content-Length"),
            required_response_headers={204: ("Upload-Offset",), 409: ("Upload-Offset",)},
        ),
        _op(
            "backend.commit_upload",
            "backend",
            "commitUpload",
            "POST",
            "/uploads/{id}/commit",
            request_schema="VersionedRequest",
            response_schemas={201: "UploadCommitted"},
            success_statuses=(201,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                409: ("CLIP_ID_COLLISION",),
                410: ("EXPIRED",),
                422: ("INTEGRITY_FAILURE",),
            },
        ),
        _op(
            "backend.get_upload",
            "backend",
            "getUpload",
            "GET",
            "/uploads/{id}",
            response_schemas={200: "UploadDetail"},
            success_statuses=(200,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                410: ("EXPIRED",),
            },
        ),
        _op(
            "backend.delete_upload",
            "backend",
            "deleteUpload",
            "DELETE",
            "/uploads/{id}",
            success_statuses=(204,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                410: ("EXPIRED",),
            },
        ),
        _op(
            "backend.create_event",
            "backend",
            "createEvent",
            "POST",
            "/events",
            request_schema="BackendEventRequest",
            response_schemas={201: "BackendEventRecord"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                409: ("IDEMPOTENCY_CONFLICT",),
            },
        ),
        _op(
            "backend.list_events",
            "backend",
            "listEvents",
            "GET",
            "/events",
            response_schemas={200: "BackendEventsPage"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 409: ("CURSOR_EXPIRED",)},
        ),
        _op(
            "backend.delete_event",
            "backend",
            "deleteEvent",
            "DELETE",
            "/events/{id}",
            success_statuses=(204,),
            error_codes={
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
            },
        ),
        _op(
            "backend.create_job",
            "backend",
            "createJob",
            "POST",
            "/jobs",
            request_schema="CreateJobRequest",
            response_schemas={201: "JobRecord"},
            success_statuses=(201,),
            error_codes={
                400: ("MALFORMED_REQUEST",),
                401: ("UNAUTHENTICATED",),
                403: ("FORBIDDEN",),
                404: ("NOT_FOUND",),
                409: ("IDEMPOTENCY_CONFLICT",),
            },
            required_request_headers=("Idempotency-Key",),
        ),
        _op(
            "backend.get_job",
            "backend",
            "getJob",
            "GET",
            "/jobs/{id}",
            response_schemas={200: "JobRecord"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 404: ("NOT_FOUND",)},
        ),
        _op(
            "backend.delete_job",
            "backend",
            "deleteJob",
            "DELETE",
            "/jobs/{id}",
            response_schemas={202: "JobCancellation"},
            success_statuses=(202,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 404: ("NOT_FOUND",)},
        ),
        _op(
            "backend.get_derivative",
            "backend",
            "getDerivative",
            "GET",
            "/derivatives/{id}",
            response_schemas={200: "DerivativeRecord"},
            success_statuses=(200,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 404: ("NOT_FOUND",)},
        ),
        _op(
            "backend.delete_derivative",
            "backend",
            "deleteDerivative",
            "DELETE",
            "/derivatives/{id}",
            response_schemas={202: "DeletingResponse"},
            success_statuses=(202,),
            error_codes={401: ("UNAUTHENTICATED",), 403: ("FORBIDDEN",), 404: ("NOT_FOUND",)},
        ),
        _op(
            "backend.get_health_live",
            "backend",
            "getHealthLive",
            "GET",
            "/health/live",
            response_schemas={200: "HealthRecord"},
            success_statuses=(200,),
            error_codes={},
        ),
        _op(
            "backend.get_health_ready",
            "backend",
            "getHealthReady",
            "GET",
            "/health/ready",
            response_schemas={200: "HealthRecord"},
            success_statuses=(200,),
            error_codes={503: ("UNAVAILABLE",)},
        ),
    )
}


ALL_OPERATIONS: Final[Mapping[str, Operation]] = {**DEVICE_OPERATIONS, **BACKEND_OPERATIONS}


def operation_for(contract: str) -> Mapping[str, Operation]:
    """Return the operation table of one contract keyed by table key."""
    return DEVICE_OPERATIONS if contract == "device" else BACKEND_OPERATIONS
