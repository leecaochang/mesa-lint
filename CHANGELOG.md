# Changelog

All notable changes to mesa-lint. Profile validation follows mesa-core; the CLI adds file diagnostics and deployment cross-checks.

## 0.2.1 - 2026-09-22

An input-handling and validation release. The linter findings were reproduced before repair and carry CLI regression tests, including machine-readable output and exit-code checks.

### Fixed

- **Automation cross-checks omitted deployment defaults.** Store scans validated `__deployment_defaults__.json` and then discarded it, so the temporary cross-check store resolved different policies from the real deployment. A switch inheriting `triggers_automations: none` from a domain override could appear in an automation trigger while the CLI reported a clean run. Validated defaults now travel with the reserved-key documents and are loaded into the cross-check store. Tests cover registry-only entities and normal profile precedence over defaults.
- **Cyclic YAML automation input produced a traceback.** A small anchor/alias cycle passed `yaml.safe_load` and recursed through the core reference walker until `RecursionError`. The core now reports a cyclic configuration as `MesaValidationError`, which the CLI maps to an explicit input error and exit 2. Ordinary shared aliases remain accepted and are covered by a control case.
- **Invalid file encodings escaped the CLI's error handling.** Profile reads caught filesystem and JSON errors but not `UnicodeDecodeError`, so an invalid UTF-8 byte produced a traceback and left `--format json` without a machine-readable result. Profile files and directory scans now report an `unreadable` finding and exit 1. Decoding failures in the auxiliary `--entities` and `--automations` inputs use the existing input-error path and exit 2. All file boundaries read UTF-8 explicitly.
- **Malformed automation-list entries were silently discarded.** `--automations` filtered out non-object entries, so `["invalid automation"]` became an empty registry and reported a clean cross-check; mixed lists checked only the usable subset without telling the operator. The loader now rejects the entire list when any entry is not an object, reports the invalid indices, and exits 2. Valid object entries are no longer checked against an incomplete registry presented as successful input.

### Changed

- **The minimum core dependency is now `mesa-core>=1.3.1`.** Lint runs receive the corrected predicate operand checks, required source validation for present origin objects, semantic routing validation, and duplicate safety-ID rejection from the repaired core validator.

### Documentation

The README now distinguishes unreadable-profile findings (exit 1) from unusable auxiliary inputs (exit 2), and explains that mixed automation lists are rejected in full. This changelog is included in the source distribution.

### Related

- `mesa-core` 1.3.1 repairs confirmation consumption, nested service snapshots, solar evaluation, inherited lease protection, profile round-trips, and atomic JSON replacement alongside the validation changes used by this release.

The earlier post-repair review found no additional linter defect; the subsequent fresh audit identified the defaults and cyclic-input cases repaired above. These changes remain in mesa-lint 0.2.1 and mesa-core 1.3.1.
