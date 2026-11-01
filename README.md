# image-kit

Shared installation capabilities and container assets for independently maintained image repositories.

中文文档：[README_zh.md](README_zh.md)

## Contents

| Path | Responsibility |
| --- | --- |
| `scripts/system/` | OS setup, users, SSH, workspaces, and package mirrors. |
| `scripts/dev/` | Build tools, compilers, developer shells, and pre-commit. |
| `scripts/python/` | Python setup and separate CUDA/Ascend package installers. |
| `scripts/libraries/` | Third-party C++ libraries. |
| `scripts/integrations/` | Ascend, ROS 2, llama.cpp, and WSLg integration. |
| `assets/` | Entrypoints, common Python development requirements, and configuration. |
| `tests/` | Non-installing argument checks and Ascend dependency-check regressions. |

Image manifests, Dockerfiles, image-specific requirements, smoke tests, build planners, schemas,
and publication policies belong to consuming repositories. This initial extraction preserves the
existing ruicx/images capability behavior; it does not reconcile Luciole-specific differences.

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
bash tests/install-arguments.sh
bash tests/ascend-pip-check.sh
mapfile -t shell_files < <(git ls-files '*.sh')
shellcheck "${shell_files[@]}"
shfmt -d -i 4 -ci "${shell_files[@]}"
```

These checks do not install software or build images. Consumers must additionally run their
manifest validation, native image builds, and smoke tests. Preserve capability behavior during
extraction; review incompatible changes separately.

## Contributions

Keep scripts grouped by capability, use English comments, retain explicit argument validation,
and update both READMEs together. Commit subjects use `Feat`, `BugFix`, `Refactor`, or `Doc`,
followed by a colon and summary; the body is a numbered list after a blank line.
