"""CLI behaviour: exit codes, formats, and cross-check flags."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mesa_lint.cli import main

VALID: dict[str, Any] = {
    "semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "semantic_tags": ["lighting.ambient"],
        "operational_boundaries": {"control_mode": "autonomous"},
    },
    "privacy_classification": {"level": "normal"},
}

INVALID: dict[str, Any] = {
    "semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "operational_boundaries": {"control_mode": "yolo"},
    }
}

WARN_ONLY: dict[str, Any] = {
    "semantic_profile": {
        "metadata_origin": {"source": "user"},
        "operational_boundaries": {"control_mode": "prohibited"},
    },
    "privacy_classification": {"level": "normal"},
}


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data))
    return path


def test_valid_sidecar_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", VALID)
    assert main([str(sidecar)]) == 0
    assert "1 profile(s) checked: 0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_invalid_sidecar_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", INVALID)
    assert main([str(sidecar)]) == 1
    assert "[E] schema" in capsys.readouterr().out


def test_warnings_pass_unless_strict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", WARN_ONLY)
    assert main([str(sidecar)]) == 0
    assert main(["--strict", str(sidecar)]) == 1


def test_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", WARN_ONLY)
    assert main(["--format", "json", str(sidecar)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"] == {"profiles": 1, "errors": 0, "warnings": 1}
    assert payload["findings"][0]["code"] == "missing-control-reason"


def test_store_directory_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.x.json", VALID)
    write(store / "lock.front.json", WARN_ONLY)
    assert main([str(store)]) == 0
    out = capsys.readouterr().out
    assert "2 profile(s) checked" in out and "missing-control-reason" in out


def test_automations_cross_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store"
    store.mkdir()
    none_profile: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {"triggers_automations": "none"},
        },
        "privacy_classification": {"level": "normal"},
    }
    write(store / "sensor.door.json", none_profile)
    automations = write(
        tmp_path / "automations.json",
        {"id": "automation.alarm", "trigger": [{"platform": "state", "entity_id": "sensor.door"}]},  # type: ignore[arg-type]
    )
    assert main([str(store), "--automations", str(automations)]) == 1
    assert "stale-none" in capsys.readouterr().out


def test_entities_orphan_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.renamed.json", VALID)
    entities = tmp_path / "entities.txt"
    entities.write_text("light.other\n")
    assert main([str(store), "--entities", str(entities)]) == 0
    assert "orphan" in capsys.readouterr().out


def test_cross_check_flags_require_directory(tmp_path: Path) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", VALID)
    automations = write(tmp_path / "a.json", {"id": "automation.x"})
    with pytest.raises(SystemExit) as exc:
        main([str(sidecar), "--automations", str(automations)])
    assert exc.value.code == 2


def test_missing_path_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nope.json")])
    assert exc.value.code == 2
