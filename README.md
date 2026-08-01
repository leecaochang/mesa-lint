# mesa-lint

Linter for [MESA](https://github.com/sfox38/mesa-core) semantic profiles. Run it in CI against the `mesa_profile.json` sidecar your Home Assistant integration ships, or point it at a mesa-core profile store directory to sweep an entire deployment.

```bash
pip install mesa-lint

mesa-lint custom_components/my_integration/mesa_profile.json   # developer CI mode
mesa-lint /config/mesa/                                        # operator store mode
```

Exit code 0 means clean, 1 means findings failed the run, 2 means usage error. Warnings do not fail the run unless you pass `--strict`.

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

As of 0.2, the automations cross-check resolves through profile inheritance: a `triggers_automations: none` declared at domain or integration scope is checked for every entity it covers, provided `--entities` names them. Store directories may contain all five scope namespaces (`__domain__:`, `__integration__:`, `__area__:`, `__device__:`); area- and device-scope declarations are linted for validity but stay inert in the cross-check, because resolving them needs HA registry mappings a CLI does not have.

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
