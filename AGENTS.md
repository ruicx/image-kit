# Agent Guidelines

## Scope and ownership

image-kit is a reusable container build tool and capability library. It must work independently
of any particular consumer repository, GitHub owner, registry, or submodule checkout path.

- `src/image_kit/` owns the Python API, CLI, manifest validation, dependency graph, change planning,
  Bake generation, smoke-test execution, and registry operations.
- `src/image_kit/schemas/` owns the packaged manifest schema. Load schema data through
  `importlib.resources`; never require a consumer-local `schemas/` directory.
- `scripts/` and `assets/` own reusable installation capabilities and container resources.
- `tests/` owns Python engine tests and shell capability tests.
- `docs/` owns the shared CLI and manifest contracts. Write these documents in English.

Consumers own image manifests, Dockerfiles, software selections, image smoke scripts, workflow
permissions, account/documentation policies, and release decisions. Do not hardcode consumer
names, paths, account defaults, or publishing destinations into the engine. Optional capabilities
such as SSH and package mirrors must remain optional for unrelated images.

## Development environment

Use Python 3.11+ and uv. Run commands from this repository's root:

```bash
uv sync --locked --extra dev
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
uv run --no-sync pytest
```

Update dependencies in `pyproject.toml` and regenerate `uv.lock` with `uv lock` when needed.
Commit both together. CI uses locked synchronization; do not bypass a stale lockfile with
`--frozen`. ty is the Python type checker; do not introduce a second type-checking setup.

All Python modules, classes, functions, and methods need English NumPy-style docstrings and
complete type annotations using modern builtin generics. Keep helpers focused and avoid global
mutable state. Preserve unrelated working-tree changes and keep edits scoped to the task.

## Contracts and compatibility

- Manifests remain the source of truth for variants, inputs, platforms, and dependencies.
  Never add handwritten image lists or dependency maps to the engine or workflows.
- Preserve CLI entry points (`images`, `image-kit`, and `python -m image_kit`), exit statuses,
  versioned plan fields, schema semantics, and published tag behavior unless intentionally
  changing a documented compatibility contract.
- Schema version 1 currently uses family/variant manifests and one native platform per family.
  Reject dependency cycles, undeclared targets, and cross-platform internal dependencies.
- Keep schema resources and `py.typed` in built wheels. Validate packaging changes with a
  non-editable installation and a consumer that has no local schema or component checkout.
- Keep registry and cache choices configurable. Never embed credentials or introduce a global
  `latest` tag. Preserve immutable published tags.
- Installation scripts use capability names, English comments, `set -euo pipefail`, and GNU
  `getopt` for parameters. Provide `--help` and return 64 for invalid usage. Verify downloaded
  binaries before installation; any exception needs explicit approval and consumer documentation.
- Consumers explicitly copy and declare each capability input and retain adjacent `COPY + RUN`
  layers. Keep image-specific branching out of Dockerfiles and inside the responsible script.

## Verification

Run the Python checks above after changing tooling or contracts. For shell changes, run on Linux
or with Git Bash, with ShellCheck and shfmt installed:

```bash
bash tests/install-arguments.sh
bash tests/ascend-pip-check.sh
mapfile -t shell_files < <(git ls-files '*.sh')
shellcheck "${shell_files[@]}"
shfmt -d -i 4 -ci "${shell_files[@]}"
```

For schema or planner changes, validate affected consumers with
`uv run images --root /path/to/consumer validate` and their repository-specific checks. Compare
generated plans and Bake definitions when preserving behavior. Unit and shell checks do not
establish that images build or run; report native image builds and hardware checks separately.

## Documentation and commits

Update `README.md` and `README_zh.md` together. Shared CLI and schema changes also update the
corresponding English guides under `docs/`. Keep consumer-specific instructions in consumer
repositories.

Use commit subjects `<Type>: <summary>`, where Type is `Feat`, `BugFix`, `Refactor`, or `Doc`.
Follow the subject with a blank line and a numbered body. Commit component changes separately
from consumer pin updates; make component commits available upstream before consumers record
their new submodule pins. Do not automatically follow a moving component branch in consumer CI.
