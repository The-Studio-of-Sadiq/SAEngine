"""Exports Secure - local delivery policies, encryption and privacy review."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.exports_common import (
    output_path,
    protect_for_current_windows_user,
    require_source,
    write_export_json,
)


def _policy_path(ctx: FeatureContext) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project to manage secure delivery settings.")
    return output_path(ctx, "delivery-policy.json", "Secure")


def _load_policy(ctx: FeatureContext) -> tuple[Path, dict[str, Any]]:
    path = _policy_path(ctx)
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"access": {}, "events": []}
        )
    except ValueError as error:
        raise FeatureInputError("Delivery policy is not valid JSON.") from error
    if not isinstance(data, dict):
        raise FeatureInputError("Delivery policy must be a JSON object.")
    data.setdefault("access", {})
    data.setdefault("events", [])
    return path, data


def _save_policy(ctx: FeatureContext, path: Path, data: dict[str, Any]) -> str:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


def _event(data: dict[str, Any], event: str, **details: Any) -> None:
    data["events"].append({"event": event, "recordedUtc": datetime.now(UTC).isoformat(), **details})


@feature(
    "exportsSecure.setPassword",
    "Set Password",
    part="settings",
    fields=[
        text("resource", "Resource path", "11 Exports/Packages/design-issue.zip"),
        text("password", "Delivery passcode", ""),
    ],
)
def set_password(ctx: FeatureContext, values: dict) -> dict:
    """Store a salted password verifier for a delivery resource without storing the password."""
    import hashlib
    import os

    if len(values["password"]) < 8:
        raise FeatureInputError("Use a passcode with at least eight characters.")
    source = require_source(ctx, values["resource"])
    salt = os.urandom(16)
    verifier = hashlib.scrypt(values["password"].encode(), salt=salt, n=2**14, r=8, p=1).hex()
    path, data = _load_policy(ctx)
    data["access"][source.relative_to(ctx.root).as_posix()] = {
        "passwordSaltHex": salt.hex(),
        "passwordVerifier": verifier,
        "hash": "scrypt-N16384-r8-p1",
        "updatedUtc": datetime.now(UTC).isoformat(),
    }
    _event(data, "password-verifier-updated", resource=source.relative_to(ctx.root).as_posix())
    return result(
        summary={
            "resource": source.relative_to(ctx.root).as_posix(),
            "policyPath": _save_policy(ctx, path, data),
            "passwordStored": False,
        },
        notes=[
            "The password itself is not stored. A verifier supports local comparison but does not password-encrypt the package bytes."
        ],
    )


@feature(
    "exportsSecure.encryptFiles",
    "Encrypt Files",
    part="settings",
    fields=[
        text("files", "Project files, one per line", "11 Exports/Packages/design-issue.zip"),
        text("suffix", "Protected-file suffix", ".dpapi"),
    ],
)
def encrypt_files(ctx: FeatureContext, values: dict) -> dict:
    """Encrypt selected files with Windows DPAPI for the current user's profile."""
    paths = [
        require_source(ctx, name.strip()) for name in values["files"].splitlines() if name.strip()
    ]
    if not paths:
        raise FeatureInputError("Select at least one file to encrypt.")
    rows = []
    for source in paths:
        suffix = values["suffix"].strip() or ".dpapi"
        target = output_path(ctx, source.name + suffix, "Secure")
        encrypted = b"SAENGINE-DPAPI/1\n" + protect_for_current_windows_user(source.read_bytes())
        target.write_bytes(encrypted)
        rows.append(
            {
                "source": source.relative_to(ctx.root).as_posix(),
                "output": target.relative_to(ctx.root).as_posix(),
                "bytes": len(encrypted),
            }
        )
    return result(
        summary={"fileCount": len(rows), "encryptedBytes": sum(row["bytes"] for row in rows)},
        tables=[
            table(
                "Protected files",
                [("source", "Source"), ("output", "Protected copy"), ("bytes", "Bytes")],
                rows,
            )
        ],
        notes=[
            "DPAPI output can only be decrypted under the same Windows user profile; source files are preserved."
        ],
    )


@feature(
    "exportsSecure.expiryDate",
    "Expiry Date",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        number("days", "Validity in days", 30, min=1, max=3650),
    ],
)
def expiry_date(ctx: FeatureContext, values: dict) -> dict:
    """Set an expiration date on a named delivery resource policy."""
    from datetime import timedelta

    now = datetime.now(UTC)
    _, data = _load_policy(ctx)
    data.setdefault("expiry", {})[values["resource"].strip()] = (
        now + timedelta(days=int(values["days"]))
    ).isoformat()
    _event(data, "expiry-set", resource=values["resource"].strip(), days=int(values["days"]))
    path = _policy_path(ctx)
    return result(
        summary={
            "resource": values["resource"],
            "expiresUtc": data["expiry"][values["resource"].strip()],
            "policyPath": _save_policy(ctx, path, data),
        }
    )


@feature(
    "exportsSecure.watermark",
    "Watermark",
    part="settings",
    fields=[
        text("source", "Text export path", "11 Exports/Packages/transmittal.md"),
        text("label", "Watermark label", "CONFIDENTIAL"),
        checkbox("dryRun", "Preview only", True),
    ],
)
def watermark(ctx: FeatureContext, values: dict) -> dict:
    """Append a visible publication label to a text export while retaining a one-time backup."""
    source = require_source(ctx, values["source"])
    if source.suffix.casefold() not in (".txt", ".md", ".csv"):
        raise FeatureInputError("Watermark supports plain text, Markdown and CSV files.")
    if source.stat().st_size > 20 * 1024 * 1024:
        raise FeatureInputError("Watermark input is limited to 20 MB.")
    data = source.read_text(encoding="utf-8")
    if not values["dryRun"]:
        backup = source.with_suffix(source.suffix + ".pre-watermark.bak")
        if not backup.exists():
            shutil.copy2(source, backup)
        source.write_text(data.rstrip() + f"\n\n[Watermark: {values['label']}]\n", encoding="utf-8")
    return result(
        summary={
            "source": source.relative_to(ctx.root).as_posix(),
            "dryRun": values["dryRun"],
            "originalBytes": len(data.encode()),
            "watermark": values["label"],
        },
        notes=[
            "A backup is made before the first edit; binary documents require a format-aware watermark tool."
        ],
    )


@feature(
    "exportsSecure.viewOnly",
    "View Only",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        checkbox("enabled", "Enable view-only policy", True),
    ],
)
def view_only(ctx: FeatureContext, values: dict) -> dict:
    """Set the requested view-only access policy for a named resource."""
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    data["access"].setdefault(resource, {})["viewOnly"] = values["enabled"]
    _event(data, "view-only-policy", resource=resource, enabled=values["enabled"])
    return result(
        summary={
            "resource": resource,
            "viewOnly": values["enabled"],
            "policyPath": _save_policy(ctx, path, data),
        },
        notes=[
            "Policy is recorded locally and requires a compatible document service to enforce it."
        ],
    )


@feature(
    "exportsSecure.allowPrinting",
    "Allow Printing",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        checkbox("allowed", "Allow printing", False),
    ],
)
def allow_printing(ctx: FeatureContext, values: dict) -> dict:
    """Set the print permission flag for a named delivery resource."""
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    data["access"].setdefault(resource, {})["allowPrinting"] = values["allowed"]
    _event(data, "printing-policy", resource=resource, allowed=values["allowed"])
    return result(
        summary={
            "resource": resource,
            "allowPrinting": values["allowed"],
            "policyPath": _save_policy(ctx, path, data),
        }
    )


@feature(
    "exportsSecure.allowCopying",
    "Allow Copying",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        checkbox("allowed", "Allow copying", False),
    ],
)
def allow_copying(ctx: FeatureContext, values: dict) -> dict:
    """Set the copy permission flag for a named delivery resource."""
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    data["access"].setdefault(resource, {})["allowCopying"] = values["allowed"]
    _event(data, "copying-policy", resource=resource, allowed=values["allowed"])
    return result(
        summary={
            "resource": resource,
            "allowCopying": values["allowed"],
            "policyPath": _save_policy(ctx, path, data),
        }
    )


@feature(
    "exportsSecure.revokeAccess",
    "Revoke Access",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        checkbox("confirm", "Confirm revocation", False),
    ],
)
def revoke_access(ctx: FeatureContext, values: dict) -> dict:
    """Revoke the local access policy entry after explicit confirmation."""
    if not values["confirm"]:
        raise FeatureInputError("Confirm access revocation before continuing.")
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    revoked = data["access"].pop(resource, None) is not None
    data.setdefault("revoked", []).append(
        {"resource": resource, "revokedUtc": datetime.now(UTC).isoformat()}
    )
    _event(data, "access-revoked", resource=resource, existed=revoked)
    return result(
        summary={
            "resource": resource,
            "revoked": revoked,
            "policyPath": _save_policy(ctx, path, data),
        },
        notes=[
            "This revokes the local policy record; revoke credentials at the connected service as well."
        ],
    )


@feature(
    "exportsSecure.deliveryLog",
    "Delivery Log",
    part="settings",
    fields=[
        text("package", "Package path", "11 Exports/Packages/design-issue.zip"),
        text("recipient", "Recipient", ""),
        select(
            "status",
            "Delivery status",
            [("prepared", "Prepared"), ("sent", "Sent"), ("failed", "Failed")],
        ),
    ],
)
def delivery_log(ctx: FeatureContext, values: dict) -> dict:
    """Record a delivery event with the exact package hash for later traceability."""
    source = require_source(ctx, values["package"])
    path, data = _load_policy(ctx)
    row = {
        "package": source.relative_to(ctx.root).as_posix(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "recipient": values["recipient"],
        "status": values["status"],
        "recordedUtc": datetime.now(UTC).isoformat(),
    }
    data.setdefault("deliveries", []).append(row)
    return result(
        summary={
            "deliveryCount": len(data["deliveries"]),
            "policyPath": _save_policy(ctx, path, data),
        },
        tables=[
            table(
                "Latest delivery",
                [
                    ("package", "Package"),
                    ("sha256", "SHA-256"),
                    ("recipient", "Recipient"),
                    ("status", "Status"),
                    ("recordedUtc", "Recorded"),
                ],
                [row],
            )
        ],
    )


@feature(
    "exportsSecure.accessLog",
    "Access Log",
    part="settings",
    fields=[text("resource", "Resource identifier filter", "")],
)
def access_log(ctx: FeatureContext, values: dict) -> dict:
    """Review locally recorded policy and delivery events for one resource."""
    _, data = _load_policy(ctx)
    resource = values["resource"].strip()
    events = [
        row for row in data.get("events", []) if not resource or row.get("resource") == resource
    ]
    deliveries = [
        row for row in data.get("deliveries", []) if not resource or row.get("package") == resource
    ]
    rows = [
        {
            "event": row.get("event", "delivery"),
            "resource": row.get("resource", row.get("package", "")),
            "recordedUtc": row.get("recordedUtc"),
            "detail": row.get("status", "policy update"),
        }
        for row in events + deliveries
    ]
    return result(
        summary={
            "eventCount": len(rows),
            "policyPath": _policy_path(ctx).relative_to(ctx.root).as_posix(),
        },
        tables=[
            table(
                "Local access and delivery events",
                [
                    ("event", "Event"),
                    ("resource", "Resource"),
                    ("recordedUtc", "Recorded"),
                    ("detail", "Detail"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsSecure.confirmReceipt",
    "Confirm Receipt",
    part="settings",
    fields=[
        text("package", "Package path", "11 Exports/Packages/design-issue.zip"),
        text("recipient", "Recipient", ""),
        text("confirmation", "Recipient confirmation reference", ""),
    ],
)
def confirm_receipt(ctx: FeatureContext, values: dict) -> dict:
    """Record an externally obtained receipt reference tied to the delivered package hash."""
    source = require_source(ctx, values["package"])
    if not values["confirmation"].strip():
        raise FeatureInputError(
            "Enter a receipt reference supplied by the recipient or delivery service."
        )
    path, data = _load_policy(ctx)
    row = {
        "package": source.relative_to(ctx.root).as_posix(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "recipient": values["recipient"],
        "confirmation": values["confirmation"].strip(),
        "confirmedUtc": datetime.now(UTC).isoformat(),
    }
    data.setdefault("receipts", []).append(row)
    return result(
        summary={
            "receiptCount": len(data["receipts"]),
            "policyPath": _save_policy(ctx, path, data),
        },
        tables=[
            table(
                "Receipt record",
                [
                    ("package", "Package"),
                    ("sha256", "SHA-256"),
                    ("recipient", "Recipient"),
                    ("confirmation", "Reference"),
                    ("confirmedUtc", "Confirmed"),
                ],
                [row],
            )
        ],
    )


@feature("exportsSecure.receiptReport", "Receipt Report", part="settings", fields=[])
def receipt_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize receipt confirmations and list outstanding delivery events."""
    _, data = _load_policy(ctx)
    receipts = data.get("receipts", [])
    received = {(row.get("package"), row.get("recipient")) for row in receipts}
    rows = []
    for delivery in data.get("deliveries", []):
        key = (delivery.get("package"), delivery.get("recipient"))
        rows.append({**delivery, "receiptConfirmed": key in received})
    return result(
        summary={
            "receiptCount": len(receipts),
            "deliveryCount": len(rows),
            "outstandingCount": sum(not row["receiptConfirmed"] for row in rows),
        },
        tables=[
            table(
                "Delivery and receipt status",
                [
                    ("package", "Package"),
                    ("recipient", "Recipient"),
                    ("status", "Delivery"),
                    ("receiptConfirmed", "Receipt confirmed"),
                    ("recordedUtc", "Recorded"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsSecure.drmServer",
    "DRM Server",
    part="settings",
    fields=[
        text("endpoint", "DRM server HTTPS endpoint", "https://example.org/drm"),
        text("tenant", "Tenant identifier", ""),
    ],
)
def drm_server(ctx: FeatureContext, values: dict) -> dict:
    """Validate and save the DRM provider endpoint and tenant configuration."""
    from urllib.parse import urlparse

    url = values["endpoint"].strip()
    if urlparse(url).scheme != "https" or not urlparse(url).netloc:
        raise FeatureInputError("DRM endpoint must be an absolute HTTPS URL.")
    path = write_export_json(
        ctx,
        "drm-server-config.json",
        {"endpoint": url, "tenant": values["tenant"].strip(), "credentialsStored": False},
        "Secure",
    )
    return result(
        summary={"configurationPath": path, "endpoint": url},
        notes=[
            "Credentials are deliberately not stored; connect through an approved DRM provider client."
        ],
    )


@feature(
    "exportsSecure.deviceLimit",
    "Device Limit",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        number("maxDevices", "Maximum devices", 2, min=1, max=100),
    ],
)
def device_limit(ctx: FeatureContext, values: dict) -> dict:
    """Set an intended concurrent-device limit in the local access policy."""
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    data["access"].setdefault(resource, {})["deviceLimit"] = int(values["maxDevices"])
    _event(data, "device-limit", resource=resource, limit=int(values["maxDevices"]))
    return result(
        summary={
            "resource": resource,
            "deviceLimit": int(values["maxDevices"]),
            "policyPath": _save_policy(ctx, path, data),
        },
        notes=["A compatible identity or DRM service must enforce device limits."],
    )


@feature(
    "exportsSecure.domainLock",
    "Domain Lock",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        text("domains", "Allowed email domains, comma separated", "example.org"),
    ],
)
def domain_lock(ctx: FeatureContext, values: dict) -> dict:
    """Set an allowlist of email domains for a resource's intended recipients."""
    domains = sorted(
        {
            item.strip().casefold().lstrip("@")
            for item in values["domains"].split(",")
            if item.strip()
        }
    )
    if not domains or any("." not in domain or " " in domain for domain in domains):
        raise FeatureInputError("Enter one or more valid email domains.")
    path, data = _load_policy(ctx)
    resource = values["resource"].strip()
    data["access"].setdefault(resource, {})["allowedDomains"] = domains
    _event(data, "domain-lock", resource=resource, domains=domains)
    return result(
        summary={
            "resource": resource,
            "domainCount": len(domains),
            "policyPath": _save_policy(ctx, path, data),
        },
        tables=[
            table("Allowed domains", [("domain", "Domain")], [{"domain": item} for item in domains])
        ],
        notes=["The allowlist is policy metadata; enforce it in the connected identity service."],
    )


@feature(
    "exportsSecure.offlineLicense",
    "Offline License",
    part="settings",
    fields=[
        text("resource", "Resource identifier", "design-issue"),
        text("licensee", "Licensee", ""),
        number("validDays", "Offline validity (days)", 7, min=1, max=365),
    ],
)
def offline_license(ctx: FeatureContext, values: dict) -> dict:
    """Issue a time-limited local offline-license record bound to a resource and licensee."""
    from datetime import timedelta

    now = datetime.now(UTC)
    license_data = {
        "resource": values["resource"],
        "licensee": values["licensee"],
        "issuedUtc": now.isoformat(),
        "expiresUtc": (now + timedelta(days=int(values["validDays"]))).isoformat(),
        "offline": True,
        "signature": "unsigned-local-record",
    }
    license_data["fingerprint"] = hashlib.sha256(
        json.dumps(license_data, sort_keys=True).encode()
    ).hexdigest()
    path = write_export_json(ctx, "offline-license.json", license_data, "Secure")
    return result(
        summary={
            "licensePath": path,
            "expiresUtc": license_data["expiresUtc"],
            "fingerprint": license_data["fingerprint"],
        },
        notes=[
            "This record is not a cryptographically signed license and needs a trusted issuer for enforcement."
        ],
    )


@feature(
    "exportsSecure.scrubMetadata",
    "Scrub Metadata",
    part="settings",
    fields=[
        text("source", "JSON file", "06 BIM/bim.json"),
        text("keys", "Metadata keys to remove, comma separated", "author,createdBy,modifiedBy"),
        text("output", "Scrubbed copy filename", "scrubbed-model.json"),
    ],
)
def scrub_metadata(ctx: FeatureContext, values: dict) -> dict:
    """Remove explicitly selected keys recursively and write a separate readable JSON copy."""
    source = require_source(ctx, values["source"])
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Source JSON cannot be parsed: {error}") from error
    keys = {item.strip() for item in values["keys"].split(",") if item.strip()}
    removed = 0

    def scrub(node: Any) -> Any:
        nonlocal removed
        if isinstance(node, list):
            return [scrub(item) for item in node]
        if isinstance(node, dict):
            clean = {}
            for key, value in node.items():
                if key in keys:
                    removed += 1
                else:
                    clean[key] = scrub(value)
            return clean
        return node

    output = scrub(data)
    path = write_export_json(
        ctx, values["output"].strip() or "scrubbed-model.json", output, "Secure"
    )
    return result(
        summary={"metadataKeysRemoved": removed, "outputPath": path},
        notes=[
            "The source JSON is preserved; only the selected metadata keys are removed from the output copy."
        ],
    )


@feature(
    "exportsSecure.redactGeometry",
    "Redact Geometry",
    part="bim",
    fields=[
        text("elementIds", "Element IDs to omit, comma separated", ""),
        text("output", "Redacted export filename", "redacted-model.json"),
    ],
)
def redact_geometry(ctx: FeatureContext, values: dict) -> dict:
    """Create a BIM copy omitting selected elements and their geometry-bearing fields."""
    raw = ctx.raw("bim")
    if not isinstance(raw, dict) or not isinstance(raw.get("elements"), list):
        raise FeatureInputError("A BIM model with elements is required.")
    omitted = {item.strip() for item in values["elementIds"].split(",") if item.strip()}
    geometry_fields = {
        "start",
        "end",
        "position",
        "outline",
        "boundary",
        "vertices",
        "faces",
        "geometry",
        "mesh",
    }
    elements, geometry_removed = [], 0
    for row in raw["elements"]:
        if not isinstance(row, dict) or str(row.get("id", "")) in omitted:
            continue
        clean = {key: value for key, value in row.items() if key not in geometry_fields}
        geometry_removed += len(row) - len(clean)
        elements.append(clean)
    path = write_export_json(
        ctx,
        values["output"].strip() or "redacted-model.json",
        {**raw, "elements": elements},
        "Secure",
    )
    return result(
        summary={
            "elementsOmitted": len(raw["elements"]) - len(elements),
            "geometryFieldsRemoved": geometry_removed,
            "outputPath": path,
        },
        notes=[
            "Redaction applies to the exported JSON copy; review linked files and derived results for additional geometry before sharing."
        ],
    )


@feature(
    "exportsSecure.purgeHistory",
    "Purge History",
    part="settings",
    fields=[
        number("keepLatest", "Keep most recent delivery events", 100, min=0, max=10000),
        checkbox("dryRun", "Preview only", True),
    ],
)
def purge_history(ctx: FeatureContext, values: dict) -> dict:
    """Remove older local delivery events after a preview or explicit non-preview run."""
    path, data = _load_policy(ctx)
    history = data.get("events", [])
    keep = int(values["keepLatest"])
    remove_count = max(0, len(history) - keep)
    if not values["dryRun"]:
        data["events"] = history[-keep:] if keep else []
        data["purgedUtc"] = datetime.now(UTC).isoformat()
        relative = _save_policy(ctx, path, data)
    else:
        relative = path.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "eventCount": len(history),
            "wouldRemove": remove_count,
            "dryRun": values["dryRun"],
            "policyPath": relative,
        }
    )


@feature(
    "exportsSecure.complianceScan",
    "Compliance Scan",
    part="settings",
    fields=[
        text("package", "Package file", "11 Exports/Packages/design-issue.zip"),
        checkbox("checkArchive", "Check ZIP integrity when applicable", True),
    ],
)
def compliance_scan(ctx: FeatureContext, values: dict) -> dict:
    """Scan a package for path traversal, archive integrity, policy records and metadata gaps."""
    import zipfile

    source = require_source(ctx, values["package"])
    findings = []
    if source.suffix.casefold() == ".zip" and values["checkArchive"]:
        try:
            with zipfile.ZipFile(source) as archive:
                for member in archive.namelist():
                    if Path(member).is_absolute() or ".." in Path(member).parts:
                        findings.append(
                            {"severity": "high", "finding": f"Unsafe archive path: {member}"}
                        )
                bad = archive.testzip()
                if bad:
                    findings.append(
                        {"severity": "high", "finding": f"CRC validation failed: {bad}"}
                    )
        except zipfile.BadZipFile:
            findings.append(
                {
                    "severity": "high",
                    "finding": "File extension is ZIP but archive cannot be opened.",
                }
            )
    _, policy = _load_policy(ctx)
    if not policy.get("access"):
        findings.append(
            {"severity": "review", "finding": "No local delivery access policy is recorded."}
        )
    if source.stat().st_size == 0:
        findings.append({"severity": "high", "finding": "Package is empty."})
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return result(
        summary={
            "package": source.relative_to(ctx.root).as_posix(),
            "sha256": digest,
            "findingCount": len(findings),
            "scanScope": "local package and policy records",
        },
        tables=[
            table(
                "Compliance findings", [("severity", "Severity"), ("finding", "Finding")], findings
            )
        ],
        notes=["This is a local technical scan, not a legal compliance certification."],
    )


@feature(
    "exportsSecure.exportCertificate",
    "Export Certificate",
    part="settings",
    fields=[
        text("files", "Files to include, one per line", "11 Exports/Packages/design-issue.zip"),
        text("reference", "Certificate reference", "CERT-001"),
    ],
)
def export_certificate(ctx: FeatureContext, values: dict) -> dict:
    """Create a readable integrity certificate record listing file hashes and issue time."""
    paths = [
        require_source(ctx, name.strip()) for name in values["files"].splitlines() if name.strip()
    ]
    if not paths:
        raise FeatureInputError("Select at least one file for the integrity certificate.")
    files = [
        {
            "path": path.relative_to(ctx.root).as_posix(),
            "sizeBytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    certificate = {
        "reference": values["reference"].strip(),
        "issuedUtc": datetime.now(UTC).isoformat(),
        "files": files,
        "signature": None,
        "status": "unsigned-integrity-record",
    }
    certificate["certificateFingerprint"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True).encode()
    ).hexdigest()
    path = write_export_json(ctx, "integrity-certificate.json", certificate, "Secure")
    return result(
        summary={
            "certificatePath": path,
            "fileCount": len(files),
            "fingerprint": certificate["certificateFingerprint"],
        },
        tables=[
            table(
                "Certified file hashes",
                [("path", "File"), ("sizeBytes", "Bytes", "byte"), ("sha256", "SHA-256")],
                files,
            )
        ],
        notes=[
            "This is a tamper-evident hash inventory, not a digital signature. A trusted signing key is needed for a signed certificate."
        ],
    )
