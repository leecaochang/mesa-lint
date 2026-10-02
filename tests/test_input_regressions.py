"""Input handling and output escaping regressions."""

import json
from pathlib import Path

import pytest

from mesa_lint.cli import main as lint_main


def test_lint_unlistable_store_directory_is_not_clean(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "light.b.json").write_text(
        json.dumps(
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"control_mode": "yolo"},
                }
            }
        )
    )
    store.chmod(0)
    try:
        assert lint_main([str(store), "--strict"]) != 0
    finally:
        store.chmod(0o755)


def test_lint_oversized_integer_is_a_finding_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sidecar = tmp_path / "big.json"
    sidecar.write_text('{"semantic_profile": {"x_big": ' + "9" * 5000 + "}}")
    code = lint_main([str(sidecar), "--format", "json"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["summary"]["errors"] >= 1


def test_lint_text_output_cannot_inject_ci_workflow_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "sensor.door.json").write_text(
        json.dumps(
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"triggers_automations": "none"},
                }
            }
        )
    )
    automations = tmp_path / "aut.json"
    automations.write_text(
        json.dumps(
            [
                {
                    "id": "x\n::error file=app.py,line=1::forged",
                    "trigger": [{"platform": "state", "entity_id": "sensor.door"}],
                }
            ]
        )
    )
    lint_main([str(store), "--automations", str(automations)])
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("::")]


def test_auxiliary_errors_keep_json_output(tmp_path, capsys):
    from mesa_lint.cli import main

    missing = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--automations", str(missing), "--format", "json"])
    assert error.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["errors"] == 1
    assert output["findings"][0]["code"] == "input"


def test_empty_path_is_rejected(capsys):
    from mesa_lint.cli import main

    with pytest.raises(SystemExit) as error:
        main(["", "--format", "json"])
    assert error.value.code == 2
    assert json.loads(capsys.readouterr().out)["summary"]["errors"] == 1


def test_missing_yaml_extra_produces_json_input_error(tmp_path, capsys, monkeypatch):
    import sys

    from mesa_lint.cli import main

    monkeypatch.setitem(sys.modules, "yaml", None)
    path = tmp_path / "AUTOMATIONS.YAML"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--automations", str(path), "--format", "json"])
    assert error.value.code == 2
    assert "yaml extra" in json.loads(capsys.readouterr().out)["findings"][0]["message"]
