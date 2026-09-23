import json

import pytest

from mesa_lint.cli import main


def test_linter_reports_bad_encoding_without_traceback(tmp_path):
    file = tmp_path / "mesa_profile.json"
    file.write_bytes(b"\xff")
    assert main([str(file), "--format", "json"]) == 1


def test_linter_rejects_malformed_automation_list(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    automations = tmp_path / "automations.json"
    automations.write_text(json.dumps(["invalid automation"]))
    with pytest.raises(SystemExit) as error:
        main([str(store), "--automations", str(automations)])
    assert error.value.code == 2


@pytest.mark.parametrize("option", ["--entities", "--automations"])
def test_auxiliary_encoding_errors_exit_two(tmp_path, option, capsys):
    store = tmp_path / "store"
    store.mkdir()
    source = tmp_path / "input.json"
    source.write_bytes(b"\xff")
    with pytest.raises(SystemExit) as error:
        main([str(store), option, str(source)])
    assert error.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_directory_encoding_error_is_json_finding(tmp_path, capsys):
    (tmp_path / "light.test.json").write_bytes(b"\xff")
    assert main([str(tmp_path), "--format", "json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["findings"][0]["code"] == "unreadable"


def test_mixed_automation_entries_report_indices(tmp_path, capsys):
    source = tmp_path / "automations.json"
    source.write_text(json.dumps([{}, "bad", None]))
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--automations", str(source)])
    assert error.value.code == 2
    assert "[1, 2]" in capsys.readouterr().err
