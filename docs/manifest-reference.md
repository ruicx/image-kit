# Image manifest v2

image-kit 0.2 loads `src/*/image.yml` using its bundled
`image_kit/schemas/image.schema.json`. The directory organizes files; YAML `name` controls
publication and dependency identity. Names must be unique across the consumer. Renaming a
directory does not rename the published image; update its explicit paths when moving files.

```yaml
schema_version: 2
name: example
description: Example development environment
dockerfile: src/example/Dockerfile
context: .
platforms: [linux/amd64, linux/arm64]
inputs: [src/example/Dockerfile]
publish: true
variants:
  - id: ubuntu24.04
    base:
      image: ubuntu:24.04
      digest: null
    build_args: {}
    tests:
      - script: src/example/tests/smoke.sh
```

| Field | Contract |
| --- | --- |
| `schema_version` | Required `2`; v1 needs explicit migration. |
| `name` | Published package name: lowercase words separated by hyphens. |
| `description` | Nonempty description. |
| `dockerfile` | Consumer-relative Dockerfile path. |
| `context` | Required `.`: all builds use the consumer root. |
| `platforms` | Nonempty unique subset of `linux/amd64` and `linux/arm64`. |
| `inputs` | File paths/globs covering all independently copied installation inputs. |
| `publish` | Whether explicitly selected variants may be published. |
| `variants` | Nonempty list of explicit environment versions; IDs unique within each name. |

| Variant field | Contract |
| --- | --- |
| `id` | Environment channel and tag prefix. Lowercase alphanumerics separated by `.`, `_` or `-`; `latest` is reserved. |
| `base.image`, `base.digest` | External image with explicit version tag and an explicit digest or `null`. |
| `base.target`, `base.context` | Internal `name/variant` and BuildKit context name; exclusive with external base fields. |
| `build_args` | Uppercase names and scalar values. Booleans become lowercase strings. `BASE_IMAGE` and `BASE_TAG` are reserved; secret-like keys are rejected. |
| `mirror` | Optional `upstream` or `aliyun`; injects `PACKAGE_MIRROR` only when declared. |
| `runtime.ssh.mode` | Optional `disabled`, `key-only` or `password`; injects `SSH_MODE` only when declared. |
| `tests` | Nonempty list of smoke contracts described below. |

An internal base is explicit:

```yaml
base:
  target: parent/ubuntu24.04
  context: parent_image
```

The engine injects `BASE_IMAGE=parent_image` and provides the same-checkout Bake context.
Dockerfiles may use `FROM ${BASE_IMAGE}` or `FROM parent_image`. The parent must support every
child platform. Cycles, missing targets and colliding normalized Bake target names are errors.
Unselected ancestors build on platforms required by selected children and stay unpublished.
An external base cannot use an unversioned reference, `latest` or `master`.

## Smoke contracts

```yaml
tests:
  - script: src/example/tests/smoke.sh
    library: src/example/tests/helpers.sh
    inputs: [src/example/tests/helpers.sh]
    policy: required
    entrypoint: image
```

`script` is required. `library` is optional and must exist beside the script and be listed in
`inputs`. Additional inputs default to an empty list. `policy` defaults to `required`;
`advisory` requires a helper that implements assertion reporting. The engine always propagates
Docker/startup failures and passes `SMOKE_HARD_GATE=1` or `0` explicitly.

`entrypoint` defaults to `bash`, overriding the image entrypoint with `/bin/bash`. `image`
retains the image entrypoint and user and runs `bash -lc`. Both mount the test directory
read-only at `/tmp/smoke`, source the optional helper and then the script, and disable pulls.
No automatic GPU/NPU device access is added. Hardware tests remain separate.

## Inputs and policy

Manifest paths, Dockerfiles, declared installation inputs, smoke scripts and smoke inputs
participate in change detection. README and Compose changes alone do not rebuild images.
Inputs must match files; absolute paths, parent traversal, Windows drive paths and symlink
escapes fail validation. YAML duplicate keys are rejected. Git diffs retain both sides of
renames. PR callers explicitly resolve the merge base before planning.

The engine always rebuilds for `.dockerignore`, `pyproject.toml`, `uv.lock` and workflow changes.
`[tool.image-kit].rebuild-inputs` adds consumer infrastructure such as component pins and
repository checks; `shell-inputs` adds explicit shell validation inputs. Registry and source
repository defaults belong in the same table. Actions caches require the explicit
`--github-cache` option; local builds omit remote cache settings by default.

Image accounts, required SSH/mirror settings, Dockerfile ARG/COPY wiring, README languages and
CI permissions are consumer policies. Consumers run those checks after `images validate`.
See [CLI and artifact contracts](cli-reference.md) and [migration](migration-v2.md).
