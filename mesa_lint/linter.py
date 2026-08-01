"""Profile lint logic: wraps mesa-core validation and adds opinionated checks.

Severity semantics: an ``error`` is a profile mesa-core itself would reject
(plus unreadable files); a ``warning`` is valid but inadvisable. The linter
never redefines validity; the ``validate_document`` in mesa-core stays the
single source of truth for what is malformed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from mesa_core import (
    HELPER_DOMAINS,
    DeploymentDefaults,
    MesaValidationError,
    ProfileStore,
    SemanticProfile,
    TriggerValidator,
    validate_document,
)
from mesa_core.backends import MemoryBackend

ERROR = "error"
WARNING = "warning"

# Beyond this, semantic_meaning prose starts costing agents real context tokens.
VERBOSE_MEANING_THRESHOLD = 400

_RESERVED_PREFIXES = ("__domain__:", "__integration__:", "__area__:", "__device__:")
_DEFAULTS_KEY = "__deployment_defaults__"


@dataclass
class Finding:
    severity: str  # ERROR or WARNING
    code: str
    message: str
    location: str

    def format_text(self) -> str:
        flag = "E" if self.severity == ERROR else "W"
        return f"{self.location}: [{flag}] {self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }


def lint_document(
    doc: dict[str, Any],
    *,
    location: str,
    entity_id: str | None = None,
    sidecar: bool = False,
) -> list[Finding]:
    """Lint one profile document. ``entity_id`` enables identity-dependent
    checks; ``sidecar`` adjusts provenance advice (Spec 5.3)."""
    findings: list[Finding] = []

    if isinstance(doc, dict) and not isinstance(doc.get("semantic_profile", doc), dict):
        # A present-but-non-object semantic_profile: mesa-core cannot load this at all.
        # mesa-core >=1.1 also reports it through validate_document, so emit only this
        # specific finding and skip the generic pass; running both would double-report
        # one defect, and nothing else is checkable on a non-object body. A non-object
        # *document* is left to validate_document below, which owns that verdict.
        sp = doc["semantic_profile"]
        findings.append(
            Finding(
                ERROR,
                "invalid-semantic-profile",
                f"semantic_profile must be an object, not {type(sp).__name__}; "
                "mesa-core cannot load this profile",
                location,
            )
        )
        return findings

    report = validate_document(doc, entity_id or "")
    findings.extend(Finding(ERROR, "schema", err, location) for err in report.errors)
    findings.extend(Finding(WARNING, "validator", warn, location) for warn in report.warnings)

    if not isinstance(doc, dict):
        # validate_document already reported "profile document must be an object".
        return findings

    sp = doc.get("semantic_profile", doc)

    ob_raw = sp.get("operational_boundaries")
    ob = ob_raw if isinstance(ob_raw, dict) else {}

    mode = ob.get("control_mode")
    if mode in ("confirm", "prohibited") and not ob.get("control_reason"):
        findings.append(
            Finding(
                WARNING,
                "missing-control-reason",
                f"control_mode: {mode} without control_reason; agents cannot "
                "explain the refusal to the user",
                location,
            )
        )

    domain = entity_id.split(".", 1)[0] if entity_id and "." in entity_id else None
    privacy = doc.get("privacy_classification") or sp.get("privacy_classification")
    if (domain == "person" or "person_traits" in sp) and privacy is None:
        findings.append(
            Finding(
                WARNING,
                "person-missing-privacy",
                "privacy_classification is required for person entities "
                "(Enrichment Section 17)",
                location,
            )
        )

    if domain in HELPER_DOMAINS and ob.get("triggers_automations") == "none":
        findings.append(
            Finding(
                WARNING,
                "helper-none",
                f"triggers_automations: none on helper domain {domain}; helpers "
                "usually exist to drive automations. Confirm with --automations "
                "cross-checking, or declare deployment_defined (Spec 5.5)",
                location,
            )
        )

    meaning = sp.get("semantic_meaning")
    if isinstance(meaning, str) and len(meaning) > VERBOSE_MEANING_THRESHOLD:
        findings.append(
            Finding(
                WARNING,
                "verbose-meaning",
                f"semantic_meaning is {len(meaning)} characters; long prose costs "
                "agent context on every retrieval. Aim for one or two sentences",
                location,
            )
        )

    if "metadata_origin" not in sp:
        if sidecar:
            message = (
                "metadata_origin absent: a sidecar defaults to source: developer. "
                "Declare it explicitly, especially if an AI helped write this "
                "profile (Spec 5.3)"
            )
        else:
            message = (
                "metadata_origin absent: this profile will be treated as "
                "source: unknown and trusted no more than an unreviewed AI "
                "guess (Spec 5.3)"
            )
        findings.append(Finding(WARNING, "missing-origin", message, location))

    return findings


def lint_store_dir(
    path: Path,
) -> tuple[list[Finding], dict[str, dict[str, Any]], dict[str, dict[str, Any]], int]:
    """Lint a JsonFileBackend profile store directory.

    Returns (findings, entity_docs, scoped_docs, profile_count). ``entity_docs``
    maps entity IDs to raw documents; ``scoped_docs`` maps full reserved keys
    (``__domain__:light``) to raw documents so the automations cross-check can
    resolve inherited declarations. File names are URL-quoted store keys, so
    reserved scope keys are recovered by unquoting.
    """
    findings: list[Finding] = []
    entity_docs: dict[str, dict[str, Any]] = {}
    scoped_docs: dict[str, dict[str, Any]] = {}
    count = 0
    for file in sorted(path.glob("*.json")):
        key = unquote(file.stem)
        location = str(file)
        count += 1
        try:
            doc = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as err:
            findings.append(Finding(ERROR, "unreadable", str(err), location))
            continue
        if key == _DEFAULTS_KEY:
            if not isinstance(doc, dict):
                # from_dict reaches for .get straight away, so a non-object raises
                # AttributeError rather than one of the malformed-input errors below.
                findings.append(
                    Finding(
                        ERROR,
                        "deployment-defaults",
                        f"malformed: expected an object, not {type(doc).__name__}",
                        location,
                    )
                )
                continue
            try:
                DeploymentDefaults.from_dict(doc)
            # mesa-core 1.2.1+ validates nested overrides and reports a
            # MesaValidationError, which is not a ValueError; older versions let
            # the raw errors through from the enum and dict lookups.
            except (MesaValidationError, ValueError, TypeError, KeyError) as err:
                findings.append(
                    Finding(ERROR, "deployment-defaults", f"malformed: {err}", location)
                )
            continue
        if any(key.startswith(prefix) for prefix in _RESERVED_PREFIXES):
            findings.extend(lint_document(doc, location=location))
            if isinstance(doc, dict):
                scoped_docs[key] = doc
            continue
        findings.extend(lint_document(doc, location=location, entity_id=key))
        entity_docs[key] = doc
    return findings, entity_docs, scoped_docs, count


# Reserved prefix, then the matching scoped setter name on ProfileStore.
_SCOPE_SETTERS = (
    ("__domain__:", "set_domain_profile"),
    ("__integration__:", "set_integration_profile"),
    ("__area__:", "set_area_profile"),
    ("__device__:", "set_device_profile"),
)


def check_automations(
    entity_docs: dict[str, dict[str, Any]],
    automations: list[dict[str, Any]],
    *,
    scoped_docs: dict[str, dict[str, Any]] | None = None,
    known_entity_ids: list[str] | None = None,
) -> list[Finding]:
    """Cross-reference declared ``triggers_automations: none`` profiles against
    automation configs (wraps mesa-core's TriggerValidator).

    ``scoped_docs`` (from ``lint_store_dir``) loads the domain, integration,
    area, and device profiles into the store, so a ``none`` an entity only
    inherits is cross-checked too. ``known_entity_ids`` names the deployment's
    entities: without it, only entities carrying their own stored profile can
    be enumerated. Structural limits, documented rather than hidden: the
    linter has no HA registry, so area and device layers resolve for nothing
    (the integration layer resolves through its domain fallback), and indirect
    automation references (device triggers, target selectors) stay invisible
    without a live registry to expand them.
    """
    store = ProfileStore(backend=MemoryBackend())
    for entity_id, doc in entity_docs.items():
        try:
            store.set(entity_id, SemanticProfile.from_dict(entity_id, doc))
        except MesaValidationError:
            continue  # already reported as a schema error
    for key, doc in (scoped_docs or {}).items():
        for prefix, setter_name in _SCOPE_SETTERS:
            if key.startswith(prefix):
                try:
                    profile = SemanticProfile.from_dict(key[len(prefix) :], doc)
                    getattr(store, setter_name)(key[len(prefix) :], profile)
                except MesaValidationError:
                    pass  # already reported as a schema error
                break
    issues = TriggerValidator(store).validate(
        lambda: automations, entity_ids=known_entity_ids
    )
    return [
        Finding(issue.severity, "stale-none", issue.recommendation, issue.entity_id)
        for issue in issues
    ]


def check_orphans(
    entity_docs: dict[str, dict[str, Any]], known_entity_ids: list[str]
) -> list[Finding]:
    """Profiles keyed by entities absent from the deployment's entity list."""
    known = set(known_entity_ids)
    return [
        Finding(
            WARNING,
            "orphan",
            f"profile is keyed by {entity_id!r}, which is not in the deployment's "
            "entity list; it applies to nothing (Spec 5.5, entity renames)",
            entity_id,
        )
        for entity_id in sorted(entity_docs)
        if entity_id not in known
    ]
