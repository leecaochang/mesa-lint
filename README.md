# mesa-lint

Linter for [MESA](https://github.com/leecaochang/mesa-core) semantic profiles. Run it in CI against the `mesa_profile.json` sidecar your Home Assistant integration ships, or point it at a mesa-core JsonFileBackend store directory to sweep an entire deployment.

注意：我不是 MESA 的原始开发者。我维护这个分支，但仅限于修复缺陷和实现已有规范，不会添加新功能。

```bash
pip install mesa-lint

mesa-lint custom_components/my_integration/mesa_profile.json   # developer CI mode
mesa-lint /config/mesa/                                        # operator store mode
```

Exit code 0 means clean, 1 means findings failed the run, 2 means usage or auxiliary-input error. Warnings do not fail the run unless you pass `--strict`.

## What it checks

**Errors** are profiles mesa-core itself would reject: invalid enums, malformed inferred profiles, bad predicate operators or temporal constraints, tag format violations, vendor tags squatting on canonical namespace roots, a non-boolean `is_minor`. The validator inside mesa-core stays the single source of truth; mesa-lint never redefines validity.

**Warnings** are valid but inadvisable: trust-laundering markers, `confirm`/`prohibited` without a `control_reason`, person entities missing their required privacy classification, `triggers_automations: none` on helper domains, `semantic_meaning` prose long enough to bloat agent context, absent `metadata_origin`.

## Cross-checks (store directories only)

```bash
# Catch stale triggers_automations: none declarations against real automations
mesa-lint /config/mesa/ --automations automations.json

# Find profiles orphaned by entity renames
mesa-lint /config/mesa/ --entities entities.txt
```

`--automations` accepts JSON natively, or YAML with `pip install 'mesa-lint[yaml]'`. `--entities` takes one entity ID per line and does double duty: it drives the orphan check and feeds the automations cross-check as the deployment's entity registry.

As of 0.2, the automations cross-check resolves through profile inheritance: domain declarations are checked against the named entities. Integration declarations resolve only through the domain-name fallback: an integration such as `zha` does not cover every `light` without HA registry mappings. Store directories may contain all four scope namespaces (`__domain__:`, `__integration__:`, `__area__:`, `__device__:`); area- and device-scope declarations are linted for validity but stay inert in the cross-check, because resolving them needs HA registry mappings a CLI does not have.

## CI usage

```yaml
- run: pip install mesa-lint
- run: mesa-lint custom_components/my_integration/mesa_profile.json --strict
```

`--format json` emits machine-readable findings for CI annotations.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check . && mypy
```

mesa-lint depends only on `mesa-core` (plus optional `pyyaml`). Apache-2.0.

## Input and output contracts

Unreadable, invalid or hostile profile files produce findings and exit 1. Unusable `--entities` or `--automations` input exits 2; `--format json` preserves machine-readable output on these failures. Text findings escape embedded newlines and control characters. Empty input paths are rejected. Empty directories warn (and fail under `--strict`); SQLite stores are unsupported and must first be exported into JSON profile files.

Store directories are checked independently, including deployment defaults. Entity registries accept a UTF-8 BOM and require at least one unique canonical entity ID. Automation input accepts a list or a single HA automation mapping; arbitrary wrapper objects are rejected. YAML suffix matching is case-insensitive, and cycles/excessive alias expansion produce controlled errors. Without PyYAML, YAML input explains how to install the extra. Template/blueprint reference coverage warnings remain visible.

Validation covers the canonical semantic-meaning locations, bounded JSON structure and diagnostics, forward-compatible access-role extensions, ISO timestamps, meaningful limits and known integration capability fields. Unknown vendor data is retained; schema validity alone does not guarantee a safe policy.
