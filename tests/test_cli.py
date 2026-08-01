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


def test_non_dict_semantic_profile_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sidecar = write(tmp_path / "mesa_profile.json", {"semantic_profile": "bad"})
    assert main([str(sidecar)]) == 1
    assert "[E] invalid-semantic-profile" in capsys.readouterr().out


def test_top_level_list_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = tmp_path / "mesa_profile.json"
    sidecar.write_text(json.dumps([1, 2, 3]))
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


def test_automations_cross_check_resolves_scoped_none_with_entities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A domain-scope none plus the --entities registry catches an inherited
    # stale none on an entity with no stored profile of its own (mesa-lint 0.2).
    from urllib.parse import quote

    store = tmp_path / "store"
    store.mkdir()
    none_profile: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {"triggers_automations": "none"},
        },
        "privacy_classification": {"level": "normal"},
    }
    write(store / f"{quote('__domain__:sensor', safe='')}.json", none_profile)
    automations = write(
        tmp_path / "automations.json",
        {"id": "automation.alarm", "trigger": [{"platform": "state", "entity_id": "sensor.door"}]},  # type: ignore[arg-type]
    )
    entities = tmp_path / "entities.txt"
    entities.write_text("sensor.door\n")
    assert main([str(store), "--automations", str(automations), "--entities", str(entities)]) == 1
    assert "stale-none" in capsys.readouterr().out

    # Without --entities the inheriting entity cannot be enumerated: exit 0.
    assert main([str(store), "--automations", str(automations)]) == 0


# ------------------- input errors exit 2, never a traceback (audit 11 F3)


def test_malformed_automations_file_is_an_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.x.json", VALID)
    bad = tmp_path / "automations.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as exc:
        main([str(store), "--automations", str(bad)])
    assert exc.value.code == 2
    assert "malformed JSON" in capsys.readouterr().err


def test_missing_input_files_are_input_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.x.json", VALID)
    for flag in ("--automations", "--entities"):
        with pytest.raises(SystemExit) as exc:
            main([str(store), flag, str(tmp_path / "nope")])
        assert exc.value.code == 2
        assert "No such file" in capsys.readouterr().err


def test_wrong_shaped_automations_file_is_an_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    write(store / "light.x.json", VALID)
    wrong = write(tmp_path / "automations.json", "not a list")  # type: ignore[arg-type]
    with pytest.raises(SystemExit) as exc:
        main([str(store), "--automations", str(wrong)])
    assert exc.value.code == 2
    assert "expected a list" in capsys.readouterr().err
