# image-kit

Manifest-driven container build tooling, installation capabilities, and assets for independent
image repositories.

中文文档：[README_zh.md](README_zh.md)

## Contents

| Path | Responsibility |
| --- | --- |
| `src/image_kit/` | Manifest validation, dependency graphs, change planning, Bake generation, tests, and registry operations. |
| `src/image_kit/schemas/` | Versioned manifest schema bundled with the Python package. |
| `scripts/system/` | OS setup, users, SSH, workspaces, and package mirrors. |
| `scripts/dev/` | Build tools, compilers, developer shells, and pre-commit. |
| `scripts/python/` | Python setup and separate CUDA/Ascend package installers. |
| `scripts/libraries/` | Third-party C++ libraries. |
| `scripts/integrations/` | Ascend, ROS 2, llama.cpp, and WSLg integration. |
| `assets/` | Entrypoints, common Python development requirements, and configuration. |
| `tests/` | Python engine tests, non-installing argument checks, and dependency-check regressions. |

Image manifests, Dockerfiles, image-specific requirements, smoke scripts, account/documentation
checks, workflow permissions, and publication policies belong to consuming repositories. The
Python package runs without a parent images checkout or a local `schemas/` directory. It supports
the family/variant v1 contract and one native platform per family; other existing manifest
formats, including Luciole's, need an explicit migration before using the engine.

## Install and run

Requires uv, Python 3.11+, Git, and Docker Buildx for image operations. Install the checked-out
component; it has not been published to PyPI. From the image-kit checkout:

```bash
uv sync --locked --extra dev
uv run images --root /path/to/image-repository validate
uv run images --root /path/to/image-repository plan --all --output build-plan.json
```

`uv run image-kit` and `uv run python -m image_kit` run the same CLI as `uv run images`. Manifests live under
`src/<family>/image.yml` in the selected consumer root. See the [manifest reference](docs/manifest-reference.md)
and [CLI reference](docs/cli-reference.md). Validation covers build contracts, paths, and the DAG;
consumer documentation and account policy are separate checks. Optional `mirror` and `runtime`
settings integrate the shared scripts; unrelated images can omit both.

Consumer defaults belong in its `pyproject.toml`, for example:

```toml
[tool.image-kit]
registry = "ghcr.io"
cache = "gha"
rebuild-inputs = [".gitmodules", "vendor/image-kit", "tools/**"]
shell-inputs = ["vendor/image-kit/tests/*.sh"]
```

The registry defaults to `ghcr.io`; registry commands accept `--registry` overrides. Omit `cache`
outside GitHub Actions. `.dockerignore`, `pyproject.toml`, `uv.lock`, and `.github/workflows/**` always trigger
rebuilds; `rebuild-inputs` adds consumer paths. Shell validation includes manifest inputs and
smoke scripts plus `shell-inputs`. The component does not assume a particular submodule path.
For uv consumers, declare `image-kit` as a dependency and use an editable path in
`[tool.uv.sources]`, then run `uv sync`. Both this project and its consumers keep their own
`uv.lock`; CI uses `uv sync --locked` and ty is the Python type checker.

## Consume a pinned component

```bash
git submodule add https://github.com/ruicx/image-kit.git vendor/image-kit
git -C vendor/image-kit checkout <reviewed-component-commit>
```

Commit the submodule pin in the consumer. Existing checkouts initialize it with
`git submodule update --init --recursive`; fresh clones can use `--recurse-submodules`.
Do not follow the component branch automatically in CI. Commit and push shared changes here
before updating a consumer pin; consumers may upgrade independently.

Use the consumer repository root as the Docker build context, copy each shared input explicitly,
and preserve adjacent capability layers:

```dockerfile
COPY --chmod=0755 vendor/image-kit/scripts/dev/cmake.sh /tmp/scripts/cmake.sh
RUN /tmp/scripts/cmake.sh --version "${CMAKE_VERSION}" --sha256 "${CMAKE_SHA256}"
```

Declare the same file in the consumer manifest's `inputs`. Parameterized scripts accept GNU
`getopt` options, provide `--help`, and return 64 for invalid usage. Consumers select versions,
base images, accounts, SSH modes, mirrors, and capability order explicitly. Credentials remain
runtime-mounted secrets. Rolling developer-shell tools and any checksum exceptions require
explicit approval and bilingual documentation in each consuming image family.

## Verification

Run on Linux or with Git Bash:

```bash
uv sync --locked --extra dev
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
bash tests/install-arguments.sh
bash tests/ascend-pip-check.sh
mapfile -t shell_files < <(git ls-files '*.sh')
shellcheck "${shell_files[@]}"
shfmt -d -i 4 -ci "${shell_files[@]}"
```

These tests do not install container software or build images. Consumers must additionally run their
manifest validation, native image builds, and smoke tests. Preserve capability behavior during
extraction; review incompatible changes separately.

## Contributions

Agents and maintainers should read [AGENTS.md](AGENTS.md) for component ownership, uv/ty checks,
compatibility requirements, and consumer boundaries.

Keep scripts grouped by capability, use English comments, retain explicit argument validation,
and update both READMEs together. Commit subjects use `Feat`, `BugFix`, `Refactor`, or `Doc`,
followed by a colon and summary; the body is a numbered list after a blank line.

## System capability options

`system.sh --timezone <zone> --upgrade <true|false>` configures the OS. Upgrading defaults to `false`; consumers opt in explicitly. Case-insensitive `true`/`false` values are accepted. `dev-tools.sh` includes `gosu` as a shared container user-switching utility; Landscape tools remain a consumer choice.
