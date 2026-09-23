"""Lint layer tests: severities, codes, and store directory handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mesa_lint.linter import (
    check_automations,
    check_orphans,
    lint_document,
    lint_store_dir,
)


def doc(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"control_mode": "autonomous"},
        },
        "privacy_classification": {"level": "normal"},
    }
    base["semantic_profile"].update(overrides)
    return base


def codes(findings: list[Any]) -> set[str]:
    return {finding.code for finding in findings}


def test_clean_profile_has_no_findings() -> None:
    assert lint_document(doc(), location="x") == []


def test_schema_error_surfaces() -> None:
    bad = doc(operational_boundaries={"control_mode": "yolo"})
    findings = lint_document(bad, location="x")
    assert any(f.severity == "error" and f.code == "schema" for f in findings)


def test_trust_laundering_is_validator_warning() -> None:
    laundered = doc(
        metadata_origin={"source": "user", "generated_at": "2026-06-01T00:00:00+00:00"}
    )
    findings = lint_document(laundered, location="x")
    assert any(f.code == "validator" and "laundering" in f.message for f in findings)


def test_non_dict_semantic_profile_is_an_error() -> None:
    findings = lint_document({"semantic_profile": "bad"}, location="x")
    assert any(f.severity == "error" and f.code == "invalid-semantic-profile" for f in findings)


def test_non_dict_semantic_profile_reports_one_error() -> None:
    # Not both invalid-semantic-profile and mesa-core's generic schema error: newer
    # mesa-core reports the non-object case too, and the two must not double up.
    findings = lint_document({"semantic_profile": "bad"}, location="x")
    errors = [f for f in findings if f.severity == "error"]
    assert len(errors) == 1
    assert errors[0].code == "invalid-semantic-profile"


def test_non_dict_document_is_reported_not_raised() -> None:
    # mesa-core owns this verdict; the linter must not crash reaching for it.
    findings = lint_document([1, 2, 3], location="x")  # type: ignore[arg-type]
    assert any(f.severity == "error" and f.code == "schema" for f in findings)


def test_missing_control_reason_warning() -> None:
    findings = lint_document(
        doc(operational_boundaries={"control_mode": "prohibited"}), location="x"
    )
    assert "missing-control-reason" in codes(findings)


def test_person_without_privacy_warning() -> None:
    bare = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "person_traits": {"is_minor": True},
        }
    }
    findings = lint_document(bare, location="x", entity_id="person.kid")
    assert "person-missing-privacy" in codes(findings)
    # With a privacy classification present, no warning.
    ok = dict(bare) | {"privacy_classification": {"level": "restricted"}}
    assert "person-missing-privacy" not in codes(lint_document(ok, location="x"))


def test_helper_none_warning_requires_entity_identity() -> None:
    helper = doc(operational_boundaries={"triggers_automations": "none"})
    with_id = lint_document(helper, location="x", entity_id="input_boolean.guest_mode")
    assert "helper-none" in codes(with_id)
    without_id = lint_document(helper, location="x")
    assert "helper-none" not in codes(without_id)


def test_verbose_meaning_warning() -> None:
    findings = lint_document(doc(semantic_meaning="x" * 500), location="x")
    assert "verbose-meaning" in codes(findings)


def test_missing_origin_message_differs_for_sidecars() -> None:
    bare = {"semantic_profile": {"semantic_tags": ["lighting.ambient"]}}
    sidecar = lint_document(bare, location="x", sidecar=True)
    store = lint_document(bare, location="x")
    sidecar_msg = next(f.message for f in sidecar if f.code == "missing-origin")
    store_msg = next(f.message for f in store if f.code == "missing-origin")
    assert "developer" in sidecar_msg
    assert "unknown" in store_msg


def test_lint_store_dir_handles_reserved_keys(tmp_path: Path) -> None:
    (tmp_path / "light.x.json").write_text(json.dumps(doc()))
    (tmp_path / f"{quote('__domain__:lock', safe='')}.json").write_text(json.dumps(doc()))
    (tmp_path / f"{quote('__device__:abc123', safe='')}.json").write_text(json.dumps(doc()))
    (tmp_path / "__deployment_defaults__.json").write_text(
        json.dumps({"deployment_defaults": {"default_control_mode": "confirm"}})
    )
    (tmp_path / "broken.json").write_text("{not json")

    findings, entity_docs, scoped_docs, count = lint_store_dir(tmp_path)
    assert count == 5
    assert set(entity_docs) == {"light.x"}  # scope and defaults keys are not entities
    assert set(scoped_docs) == {"__domain__:lock", "__device__:abc123", "__deployment_defaults__"}
    assert any(f.code == "unreadable" for f in findings)
    # Scope docs are linted without entity identity: no helper/person misfires
    # from the pseudo entity_id a reserved key would otherwise split into.
    assert not any(f.code == "helper-none" for f in findings)


def test_lint_store_dir_flags_bad_deployment_defaults(tmp_path: Path) -> None:
    (tmp_path / "__deployment_defaults__.json").write_text(
        json.dumps({"deployment_defaults": {"default_control_mode": "yolo"}})
    )
    findings, _, _, _ = lint_store_dir(tmp_path)
    assert any(f.code == "deployment-defaults" for f in findings)


def test_lint_store_dir_flags_non_object_deployment_defaults(tmp_path: Path) -> None:
    (tmp_path / "__deployment_defaults__.json").write_text(json.dumps([1, 2, 3]))
    findings, _, _, _ = lint_store_dir(tmp_path)
    assert any(f.severity == "error" and f.code == "deployment-defaults" for f in findings)


def test_check_automations_wraps_trigger_validator() -> None:
    none_doc = doc(operational_boundaries={"triggers_automations": "none"})
    automations = [
        {
            "id": "automation.guest",
            "trigger": [{"platform": "state", "entity_id": "input_boolean.guest_mode"}],
        }
    ]
    findings = check_automations({"input_boolean.guest_mode": none_doc}, automations)
    assert len(findings) == 1
    assert findings[0].code == "stale-none" and findings[0].severity == "error"


def test_check_orphans() -> None:
    findings = check_orphans({"light.gone": doc(), "light.kept": doc()}, ["light.kept"])
    assert [f.location for f in findings] == ["light.gone"]
    assert all(f.code == "orphan" for f in findings)


def test_check_automations_resolves_inherited_none_from_domain_scope() -> None:
    # A none declared only at domain scope was previously never cross-checked:
    # the entity has no stored profile of its own, and scoped docs were dropped.
    automations = [
        {
            "id": "automation.evening",
            "trigger": [{"platform": "state", "entity_id": "light.porch"}],
        }
    ]
    none_doc = doc(operational_boundaries={"triggers_automations": "none"})
    findings = check_automations(
        {},
        automations,
        scoped_docs={"__domain__:light": none_doc},
        known_entity_ids=["light.porch"],
    )
    assert len(findings) == 1
    assert findings[0].code == "stale-none" and findings[0].location == "light.porch"

    # Without the entity registry the inheriting entity cannot be enumerated.
    assert (
        check_automations({}, automations, scoped_docs={"__domain__:light": none_doc}) == []
    )


def test_check_automations_resolves_inherited_none_from_integration_scope() -> None:
    # Integration scope resolves through the domain fallback when the name is
    # domain-defining (Spec 5.6), which is all the linter can do with no registry.
    automations = [
        {
            "id": "automation.evening",
            "trigger": [{"platform": "state", "entity_id": "light.porch"}],
        }
    ]
    none_doc = doc(operational_boundaries={"triggers_automations": "none"})
    findings = check_automations(
        {},
        automations,
        scoped_docs={"__integration__:light": none_doc},
        known_entity_ids=["light.porch"],
    )
    assert len(findings) == 1 and findings[0].location == "light.porch"


def test_check_automations_tolerates_area_and_device_scopes() -> None:
    # Area and device layers are inert without HA registry mappings; their
    # presence must neither crash nor produce spurious findings.
    automations = [
        {
            "id": "automation.evening",
            "trigger": [{"platform": "state", "entity_id": "light.porch"}],
        }
    ]
    none_doc = doc(operational_boundaries={"triggers_automations": "none"})
    findings = check_automations(
        {},
        automations,
        scoped_docs={
            "__area__:area.porch": none_doc,
            "__device__:abc123": none_doc,
        },
        known_entity_ids=["light.porch"],
    )
    assert findings == []
