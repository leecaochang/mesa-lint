"""mesa-lint command line interface.

Exit codes: 0 clean (warnings allowed unless --strict), 1 findings failed the
run, 2 usage or input errors.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, NoReturn

from mesa_core.exceptions import MesaValidationError
from mesa_core.json_io import check_structure, loads
from mesa_core.store import validate_entity_id

from mesa_lint.linter import (
    ERROR,
    WARNING,
    Finding,
    check_automations,
    check_orphans,
    lint_document,
    lint_store_dir,
)

_OUTPUT_FORMAT: ContextVar[str] = ContextVar("mesa_lint_format", default="text")


def _input_error(message: str) -> NoReturn:
    """Report a usage or input error and exit 2, the documented contract.

    ``SystemExit(message)`` prints the message but exits 1, which reads in CI
    as "the lint run found problems" rather than "the input was unusable", so
    the code is set explicitly.
    """
    if _OUTPUT_FORMAT.get() == "json":
        print(
            json.dumps(
                {
                    "findings": [Finding(ERROR, "input", message, "input").to_dict()],
                    "summary": {"profiles": 0, "errors": 1, "warnings": 0},
                }
            )
        )
    else:
        print(Finding(ERROR, "input", message, "input").format_text(), file=sys.stderr)
    raise SystemExit(2)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as err:
        _input_error(f"{path}: {err}")


def _load_automations(path: Path) -> list[dict[str, Any]]:
    text = _read_text(path)
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            _input_error(
                f"{path}: YAML input requires the yaml extra (pip install 'mesa-lint[yaml]')"
            )
        try:
            data = yaml.safe_load(text)
            check_structure(data)
        except (yaml.YAMLError, MesaValidationError, ValueError, RecursionError) as err:
            _input_error(f"{path}: malformed YAML: {err}")
    else:
        try:
            data = loads(text)
        except MesaValidationError as err:
            _input_error(f"{path}: malformed JSON: {err}")
    if isinstance(data, dict) and set(data) & {
        "trigger",
        "triggers",
        "condition",
        "conditions",
        "action",
        "actions",
        "use_blueprint",
    }:
        data = [data]
    if not isinstance(data, list):
        _input_error(f"{path}: expected a list of automation configs")
    invalid = [i for i, config in enumerate(data) if not isinstance(config, dict)]
    if invalid:
        _input_error(f"{path}: automation entries at indices {invalid} must be objects")
    if any("id" in config and not isinstance(config["id"], str | int) for config in data):
        _input_error(f"{path}: automation id must be a string or integer")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mesa-lint",
        description=(
            "Lint MESA semantic profiles: mesa_profile.json sidecars (files) "
            "and mesa-core JsonFileBackend profile stores (directories)."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="mesa_profile.json files and/or profile store directories",
    )
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--automations",
        type=Path,
        help=(
            "automation configs (JSON, or YAML with the yaml extra) to "
            "cross-reference against triggers_automations: none declarations; "
            "requires a store directory input"
        ),
    )
    parser.add_argument(
        "--entities",
        type=Path,
        help=(
            "file with one entity ID per line; profiles keyed by entities not "
            "listed are reported as orphans, and the list also feeds the "
            "--automations cross-check as the deployment's entity registry; "
            "requires a store directory input"
        ),
    )
    args = parser.parse_args(argv)

    token = _OUTPUT_FORMAT.set(args.format)
    try:
        return _run(args)
    finally:
        _OUTPUT_FORMAT.reset(token)


def _run(args: argparse.Namespace) -> int:
    findings: list[Finding] = []
    entity_docs: dict[str, dict[str, Any]] = {}
    scoped_docs: dict[str, dict[str, Any]] = {}
    stores: list[tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]] = []
    profile_count = 0
    saw_dir = False
    for raw_path in args.paths:
        if not raw_path:
            _input_error("empty input path")
        path = Path(raw_path)
        try:
            mode = path.stat().st_mode
            is_dir, is_file = stat.S_ISDIR(mode), stat.S_ISREG(mode)
        except FileNotFoundError:
            _input_error(f"{path}: no such file or directory")
        except OSError as err:
            findings.append(Finding(ERROR, "unreadable", str(err), str(path)))
            continue
        if is_dir:
            saw_dir = True
            dir_findings, docs, scoped, count = lint_store_dir(path)
            findings.extend(dir_findings)
            stores.append((docs, scoped))
            profile_count += count
        elif is_file:
            profile_count += 1
            try:
                doc = loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, MesaValidationError) as err:
                findings.append(Finding(ERROR, "unreadable", str(err), str(path)))
                continue
            findings.extend(lint_document(doc, location=str(path), sidecar=True))
        else:
            _input_error(f"{path}: no such file or directory")

    known: list[str] | None = None
    if args.entities is not None:
        if not saw_dir:
            _input_error("--entities requires a profile store directory input")
        known = [line.strip() for line in _read_text(args.entities).splitlines() if line.strip()]
        if not known or len(set(known)) != len(known):
            _input_error(f"{args.entities}: entity registry must be non-empty without duplicates")
        try:
            for entity_id in known:
                validate_entity_id(entity_id)
        except MesaValidationError as err:
            _input_error(f"{args.entities}: {err}")
    if args.automations is not None:
        if not saw_dir:
            _input_error("--automations requires a profile store directory input")
        try:
            automations = _load_automations(args.automations)
            for entity_docs, scoped_docs in stores:
                findings.extend(
                    check_automations(
                        entity_docs,
                        automations,
                        scoped_docs=scoped_docs,
                        known_entity_ids=known,
                    )
                )
        except MesaValidationError as err:
            _input_error(f"{args.automations}: {err}")
    if known is not None:
        for entity_docs, _ in stores:
            findings.extend(check_orphans(entity_docs, known))

    errors = sum(1 for finding in findings if finding.severity == ERROR)
    warnings = sum(1 for finding in findings if finding.severity == WARNING)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "findings": [finding.to_dict() for finding in findings],
                    "summary": {
                        "profiles": profile_count,
                        "errors": errors,
                        "warnings": warnings,
                    },
                },
                indent=2,
            )
        )
    else:
        for finding in findings:
            print(finding.format_text())
        print(f"{profile_count} profile(s) checked: {errors} error(s), {warnings} warning(s)")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
