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

from dataclasses import dataclass, field, replace
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


#: The media type of every JSON body of both contracts (interfaces.md §1).
JSON_CONTENT_TYPE: Final[str] = "application/json"

#: The media type of a raw byte body: the chunk of a PATCH and the deferred OTA image.
BINARY_CONTENT_TYPE: Final[str] = "application/octet-stream"

#: The media type of the live preview stream, exactly as interfaces.md §3 spells it
#: (the ``boundary`` parameter is part of what the document publishes, not decoration).
PREVIEW_CONTENT_TYPE: Final[str] = "multipart/x-mixed-replace; boundary=frame"


@dataclass(frozen=True)
class Operation:
    """One documented operation of one contract."""

    key: str
    contract: str
    operation_id: str
    method: str
    path: str
    request_schema: str | None = None
    #: Body schema per documented status. A status of 400 or above normally carries the
    #: shared ``Error`` envelope and so is absent here, which is exactly what tells
    #: :mod:`tools.contracts.api_validate` to check it as one; a rejection that binds its
    #: own schema — ``PUT /settings``' 409, which names the revision the client lost the
    #: race to — is recorded here and checked against that schema instead.
    response_schemas: Mapping[int, str | None] = field(default_factory=dict)
    success_statuses: tuple[int, ...] = ()
    error_codes: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    required_request_headers: tuple[str, ...] = ()
    required_response_headers: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    #: Headers a response of this status may carry because the contract documents them
    #: without requiring them. A header rule accepts such a header only here, so a
    #: conforming preview answer is not refused and an invented one elsewhere is.
    documented_response_headers: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    #: Media types of a documented request body that is not the bound JSON schema: the
    #: raw chunk of a PATCH upload and the deferred OTA image.
    request_content_types: tuple[str, ...] = ()
    #: Media types of a documented response body that is not a JSON schema: the preview
    #: multipart stream and the two binary file downloads, per status.
    response_content_types: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    body_bound_bytes: int | None = None

    @property
    def documented_statuses(self) -> tuple[int, ...]:
        """Every status the spec assigns this operation, sorted."""
        return tuple(sorted(set(self.success_statuses) | set(self.error_codes)))

    @property
    def is_head(self) -> bool:
        """True for the operation whose answer is headers and status alone."""
        return self.method.upper() == "HEAD"

    def allowed_codes_for(self, status: int) -> frozenset[str]:
        """Codes the spec (or the documented illustrative set) allows for a status."""
        listed = self.error_codes.get(status, ())
        return frozenset(listed) | ILLUSTRATIVE_CODES

    def content_types_for(self, direction: str, status: int | None) -> frozenset[str]:
        """Media types the contract documents for one direction and status.

        The two documents publish exactly these: a JSON body carries the bound schema,
        the preview 200 carries its multipart, the file downloads carry octet-stream,
        the raw chunk and deferred image carry octet-stream, and a HEAD answer or a
        204 carries nothing at all (RFC 9110 §9.3.2, §15.3.3). A ``Content-Type``
        outside this set is a value the selected operation never promised.
        """
        if direction == "request":
            if self.request_schema is not None:
                return frozenset({JSON_CONTENT_TYPE})
            return frozenset(self.request_content_types)
        if status is None:
            return frozenset()
        if status in self.response_content_types:
            return frozenset(self.response_content_types[status])
        if status in self.response_schemas:
            return frozenset({JSON_CONTENT_TYPE}) if self.response_schemas[status] else frozenset()
        if status in self.error_codes:
            # A HEAD refusal is still a HEAD: no content, so no media type either.
            return frozenset() if self.is_head else frozenset({JSON_CONTENT_TYPE})
        return frozenset()


def _op(key: str, contract: str, operation_id: str, method: str, path: str, **kwargs: object) -> Operation:
    return Operation(key=key, contract=contract, operation_id=operation_id, method=method, path=path, **kwargs)  # type: ignore[arg-type]


#: The header every documented 401 of both contracts carries, named once here because
#: it is one rule of RFC 9110 §15.5.2 rather than per-operation discretion: a 401 that
#: does not say how to authenticate is not a challenge. The two OpenAPI documents
#: declare it on the shared `Unauthorized` response (and on the bodyless HEAD refusal
#: that cannot use that response), and :func:`openapi_check.check_operation` fails the
#: document if this table ever claims a header the document does not require.
WWW_AUTHENTICATE_HEADER: Final[str] = "WWW-Authenticate"


def _requiring_bearer_challenge(op: Operation) -> Operation:
    """Add the bearer challenge to the required headers of a documented 401.

    Applied to the whole table rather than spelled per operation, so a new operation
    that documents a 401 cannot forget the header the way it could forget a line.
    """
    if 401 not in op.error_codes:
        return op
    headers = dict(op.required_response_headers)
    headers[401] = tuple(dict.fromkeys((*headers.get(401, ()), WWW_AUTHENTICATE_HEADER)))
    return replace(op, required_response_headers=headers)


DEVICE_OPERATIONS: Final[dict[str, Operation]] = {
    op.key: _requiring_bearer_challenge(op)
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
            # interfaces.md §1-2: the claim window is opened by a qualified physical
            # control, so a pairing attempt outside that window is refused with 403
            # (the same status §1 assigns to "wrong privilege/physical window").
            error_codes={
                400: ("MALFORMED_REQUEST",),
                403: ("FORBIDDEN",),
                409: ("ALREADY_OWNED",),
                429: ("RATE_LIMITED",),
            },
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
            # The 409 is the one rejection of either contract that says more than the
            # shared envelope: interfaces.md promises the current revision alongside
            # REVISION_CONFLICT, and the closed Error schema has no member for it.
            response_schemas={200: "PutSettingsResponse", 409: "SettingsRevisionConflictResponse"},
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
            # device-v1.yaml documents `Cache-Control` on the 200 with a `no-store`
            # const (components/headers/CacheControlNoStore) and does not mark it
            # required, so it is allowed here and nowhere else.
            documented_response_headers={200: ("Cache-Control",)},
            response_content_types={200: (PREVIEW_CONTENT_TYPE,)},
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
            # device-v1.yaml serves both range answers as raw `application/octet-stream`
            # (the manifest summary's own media type), so those are the only media types
            # this operation may name.
            response_content_types={200: (BINARY_CONTENT_TYPE,), 206: (BINARY_CONTENT_TYPE,)},
        ),
        _op(
            "device.post_ota",
            "device",
            "postOta",
            "POST",
            "/ota",
            response_schemas={202: "OtaStageResponse"},
            success_statuses=(202,),
            # device-v1.yaml documents the image itself as `application/octet-stream`;
            # there is no JSON request schema on this operation, so that raw media type
            # is the only one a request here may carry.
            request_content_types=(BINARY_CONTENT_TYPE,),
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
    op.key: _requiring_bearer_challenge(op)
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
            # backend-v1.yaml serves both range answers as raw `application/octet-stream`,
            # so those are the only media types this operation may name.
            response_content_types={200: (BINARY_CONTENT_TYPE,), 206: (BINARY_CONTENT_TYPE,)},
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
            # backend-v1.yaml serves both range answers as raw `application/octet-stream`,
            # so those are the only media types this operation may name.
            response_content_types={200: (BINARY_CONTENT_TYPE,), 206: (BINARY_CONTENT_TYPE,)},
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
                # interfaces.md §8: an upload whose session has expired has already
                # answered 410 on HEAD and commit, and a chunk that arrives after the
                # window closes is the same refusal — the session is gone, so the
                # offset it was writing at is gone with it.
                410: ("EXPIRED",),
                413: ("BOUND_EXCEEDED",),
                422: ("INTEGRITY_FAILURE",),
            },
            required_request_headers=("Upload-Offset", "Upload-Checksum", "Content-Length"),
            required_response_headers={204: ("Upload-Offset",), 409: ("Upload-Offset",)},
            # backend-v1.yaml §/uploads/{id}/files/{name} PATCH documents exactly one
            # media type for the chunk: `application/octet-stream` of 1-1,048,576 bytes.
            request_content_types=(BINARY_CONTENT_TYPE,),
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
