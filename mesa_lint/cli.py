"""mesa-lint command line interface.

Exit codes: 0 clean (warnings allowed unless --strict), 1 findings failed the
run, 2 usage or input errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from mesa_core.exceptions import MesaValidationError

from mesa_lint.linter import (
    ERROR,
    WARNING,
    Finding,
    check_automations,
    check_orphans,
    lint_document,
    lint_store_dir,
)


def _input_error(message: str) -> NoReturn:
    """Report a usage or input error and exit 2, the documented contract.

    ``SystemExit(message)`` prints the message but exits 1, which reads in CI
    as "the lint run found problems" rather than "the input was unusable", so
    the code is set explicitly.
    """
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as err:
        _input_error(f"{path}: {err}")


def _load_automations(path: Path) -> list[dict[str, Any]]:
    text = _read_text(path)
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            _input_error(
                f"{path}: YAML input requires the yaml extra "
                "(pip install 'mesa-lint[yaml]')"
            )
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as err:
            _input_error(f"{path}: malformed YAML: {err}")
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            _input_error(f"{path}: malformed JSON: {err}")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        _input_error(f"{path}: expected a list of automation configs")
    invalid = [i for i, config in enumerate(data) if not isinstance(config, dict)]
    if invalid:
        _input_error(f"{path}: automation entries at indices {invalid} must be objects")
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
        type=Path,
        help="mesa_profile.json files and/or profile store directories",
    )
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as failures"
    )
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

    findings: list[Finding] = []
    entity_docs: dict[str, dict[str, Any]] = {}
    scoped_docs: dict[str, dict[str, Any]] = {}
    profile_count = 0
    saw_dir = False
    for path in args.paths:
        if path.is_dir():
            saw_dir = True
            dir_findings, docs, scoped, count = lint_store_dir(path)
            findings.extend(dir_findings)
            entity_docs.update(docs)
            scoped_docs.update(scoped)
            profile_count += count
        elif path.is_file():
            profile_count += 1
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as err:
                findings.append(Finding(ERROR, "unreadable", str(err), str(path)))
                continue
            findings.extend(lint_document(doc, location=str(path), sidecar=True))
        else:
            parser.error(f"{path}: no such file or directory")

    known: list[str] | None = None
    if args.entities is not None:
        if not saw_dir:
            parser.error("--entities requires a profile store directory input")
        known = [
            line.strip() for line in _read_text(args.entities).splitlines() if line.strip()
        ]
    if args.automations is not None:
        if not saw_dir:
            parser.error("--automations requires a profile store directory input")
        try:
            findings.extend(
                check_automations(
                    entity_docs,
                    _load_automations(args.automations),
                    scoped_docs=scoped_docs,
                    known_entity_ids=known,
                )
            )
        except MesaValidationError as err:
            _input_error(f"{args.automations}: {err}")
    if known is not None:
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
