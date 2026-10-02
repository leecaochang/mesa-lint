"""Behavior contracts derived from the October audit mutation witnesses."""

import json
from urllib.parse import quote

import pytest

from mesa_lint.cli import main
from mesa_lint.linter import lint_document, lint_store_dir


def doc(**overrides):
    base = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"control_mode": "autonomous"},
        },
        "privacy_classification": {"level": "normal"},
    }
    base["semantic_profile"].update(overrides)
    return base


def codes(findings):
    return {f.code for f in findings}


def write(path, data):
    path.write_text(json.dumps(data))
    return path


def test_confirm_without_reason_warns():
    findings = lint_document(doc(operational_boundaries={"control_mode": "confirm"}), location="x")
    assert "missing-control-reason" in codes(findings)


def test_exactly_400_characters_does_not_warn_and_401_does():
    assert "verbose-meaning" not in codes(
        lint_document(doc(semantic_meaning="x" * 400), location="x")
    )
    assert "verbose-meaning" in codes(lint_document(doc(semantic_meaning="x" * 401), location="x"))


def test_person_traits_on_a_non_person_entity_needs_privacy():
    bare = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "person_traits": {"is_minor": True},
        }
    }
    assert "person-missing-privacy" in codes(
        lint_document(bare, location="x", entity_id="sensor.kid")
    )


def test_nested_privacy_classification_satisfies_person_check():
    nested = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "privacy_classification": {"level": "restricted"},
        }
    }
    assert "person-missing-privacy" not in codes(
        lint_document(nested, location="x", entity_id="person.kid")
    )


def test_validator_warnings_stay_warnings():
    laundered = doc(metadata_origin={"source": "user", "generated_at": "2026-06-01T00:00:00+00:00"})
    findings = [f for f in lint_document(laundered, location="x") if f.code == "validator"]
    assert findings and all(f.severity == "warning" for f in findings)


def test_validator_warning_does_not_fail_a_non_strict_run(tmp_path):
    sidecar = write(
        tmp_path / "mesa_profile.json",
        doc(metadata_origin={"source": "user", "generated_at": "2026-06-01T00:00:00+00:00"}),
    )
    assert main([str(sidecar)]) == 0


@pytest.mark.parametrize("prefix", ["__integration__:", "__area__:", "__domain__:", "__device__:"])
def test_every_scope_prefix_is_kept_out_of_entity_docs(tmp_path, prefix):
    (tmp_path / f"{quote(prefix + 'x', safe='')}.json").write_text(json.dumps(doc()))
    _, entity_docs, scoped_docs, _ = lint_store_dir(tmp_path)
    assert entity_docs == {}
    assert list(scoped_docs) == [prefix + "x"]


def test_non_object_scoped_doc_does_not_crash_the_cross_check(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / f"{quote('__domain__:light', safe='')}.json").write_text(json.dumps([1, 2, 3]))
    automations = write(tmp_path / "a.json", [{"id": "automation.x"}])
    assert main([str(store), "--automations", str(automations)]) in (0, 1)


def test_invalid_entity_profile_is_a_finding_not_an_input_error(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    write(
        store / "light.bad.json",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "yolo"},
            }
        },
    )
    automations = write(tmp_path / "a.json", [{"id": "automation.x"}])
    assert main([str(store), "--automations", str(automations)]) == 1  # schema error, not exit 2


def test_invalid_scoped_profile_is_a_finding_not_an_input_error(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    write(
        store / f"{quote('__domain__:light', safe='')}.json",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "yolo"},
            }
        },
    )
    automations = write(tmp_path / "a.json", [{"id": "automation.x"}])
    assert main([str(store), "--automations", str(automations)]) == 1


def test_entities_flag_requires_a_directory(tmp_path):
    sidecar = write(tmp_path / "mesa_profile.json", doc())
    entities = tmp_path / "e.txt"
    entities.write_text("light.x\n")
    with pytest.raises(SystemExit) as exc:
        main([str(sidecar), "--entities", str(entities)])
    assert exc.value.code == 2


def test_empty_entity_registry_is_an_input_error(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.x.json", doc())
    entities = tmp_path / "e.txt"
    entities.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(store), "--entities", str(entities)])
    assert exc.value.code == 2


def test_malformed_yaml_is_an_input_error(tmp_path, capsys):
    yaml = pytest.importorskip("yaml")  # noqa: F841
    store = tmp_path / "store"
    store.mkdir()
    bad = tmp_path / "a.yaml"
    bad.write_text("a: [unclosed\n")
    with pytest.raises(SystemExit) as exc:
        main([str(store), "--automations", str(bad)])
    assert exc.value.code == 2
    assert "malformed YAML" in capsys.readouterr().err


def test_sidecar_files_get_sidecar_advice(tmp_path, capsys):
    sidecar = write(
        tmp_path / "mesa_profile.json",
        {"semantic_profile": {"semantic_tags": ["lighting.ambient"]}},
    )
    main([str(sidecar)])
    assert "sidecar defaults to source: developer" in capsys.readouterr().out
