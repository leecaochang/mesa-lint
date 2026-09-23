"""Independent expected-behavior tests from the fresh audit. Source stays unchanged."""

import json

import pytest
from mesa_core import ProfileStore, TriggerValidator
from mesa_core.backends import JsonFileBackend

from mesa_lint.cli import main


def document(**boundaries):
    return {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {"control_mode": "autonomous", **boundaries},
        }
    }


def test_linter_uses_deployment_default_none(tmp_path, capsys):
    folder = tmp_path / "store"
    folder.mkdir()
    defaults = {
        "deployment_defaults": {"domain_overrides": {"switch": {"triggers_automations": "none"}}}
    }
    (folder / "__deployment_defaults__.json").write_text(json.dumps(defaults))
    automations = [{"id": "real", "triggers": [{"trigger": "state", "entity_id": "switch.test"}]}]
    automation_file = tmp_path / "automations.json"
    automation_file.write_text(json.dumps(automations))
    entities = tmp_path / "entities.txt"
    entities.write_text("switch.test\n")
    # The real store and core validator both recognize this declaration.
    store = ProfileStore(JsonFileBackend(folder))
    assert (
        store.get_effective("switch.test").operational_boundaries.triggers_automations.value
        == "none"
    )
    assert (
        len(TriggerValidator(store).validate(lambda: automations, entity_ids=["switch.test"])) == 1
    )
    code = main(
        [
            str(folder),
            "--automations",
            str(automation_file),
            "--entities",
            str(entities),
            "--format",
            "json",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 1, report
    assert any(item["code"] == "stale-none" for item in report["findings"])


def test_recursive_yaml_is_a_controlled_input_error(tmp_path):
    folder = tmp_path / "store"
    folder.mkdir()
    automation_file = tmp_path / "automations.yaml"
    automation_file.write_text("- id: cyclic\n  trigger: &loop\n    nested: *loop\n")
    with pytest.raises(SystemExit) as caught:
        main([str(folder), "--automations", str(automation_file)])
    assert caught.value.code == 2


def test_shared_yaml_alias_is_accepted(tmp_path):
    folder = tmp_path / "store"
    folder.mkdir()
    source = tmp_path / "automations.yaml"
    source.write_text(
        "- id: shared\n  trigger: &shared\n    entity_id: switch.test\n  condition: *shared\n"
    )
    assert main([str(folder), "--automations", str(source)]) == 0


@pytest.mark.parametrize("mode,expected", [("likely", 0), ("none", 1)])
def test_default_crosscheck_respects_profile_precedence(tmp_path, mode, expected):
    folder = tmp_path / "store"
    folder.mkdir()
    (folder / "__deployment_defaults__.json").write_text(
        json.dumps(
            {
                "deployment_defaults": {
                    "domain_overrides": {"switch": {"triggers_automations": "none"}}
                }
            }
        )
    )
    (folder / "switch.test.json").write_text(json.dumps(document(triggers_automations=mode)))
    source = tmp_path / "automations.json"
    source.write_text(json.dumps([{"id": "real", "trigger": {"entity_id": "switch.test"}}]))
    assert main([str(folder), "--automations", str(source)]) == expected
