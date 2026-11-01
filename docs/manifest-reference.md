# Image manifest reference

`src/<family>/image.yml` is the versioned release contract for an image family. Paths and glob
patterns are relative to the repository root. Unknown fields are rejected.

## Shared installation scripts

Scripts under `vendor/image-kit/scripts/` are grouped by capability in one directory level:

| Directory | Responsibility |
| --- | --- |
| `system/` | OS configuration, accounts, SSH, workspace, and package mirrors. |
| `python/` | Python setup and package installation. |
| `dev/` | Developer tools, compilers, build tools, and shell setup. |
| `libraries/` | Third-party C++ libraries. |
| `integrations/` | Platform and application integration, including Ascend, ROS 2, llama.cpp, and WSLg. |

Platform-specific scripts keep a prefix, such as `python/cuda-pip-packages.sh` and
`python/ascend-pip-packages.sh`; there is no additional platform directory level.
Directory names do not determine execution order: each Dockerfile keeps explicit, independent
`COPY + RUN` steps and each consuming manifest lists the exact script paths in `inputs`.
Scripts without a current image consumer remain available for future use.

## Family fields

| Field | Type | Contract |
| --- | --- | --- |
| `schema_version` | integer | Must be `1`. A future incompatible format increments this value. |
| `name` | string | Lowercase kebab-case and identical to `<family>`. |
| `description` | string | Non-empty, user-facing family summary. |
| `dockerfile` | path | Existing Dockerfile inside the repository. |
| `context` | path | Existing build context inside the repository. |
| `platforms` | list | Exactly one platform: `linux/amd64` or `linux/arm64`. Internal dependencies must use the same platform. |
| `inputs` | list | Existing path/glob patterns whose changes rebuild every family variant. |
| `publish` | boolean | Allows selected variants to be published from `main`. |
| `variants` | list | One or more variant definitions. |

## Variant fields

| Field | Type | Contract |
| --- | --- | --- |
| `id` | string | Floating tag name; lowercase segments separated by `.`, `_`, or `-`; never `latest`. |
| `base.image` | string | External image with an explicit version tag; `latest` and `master` are forbidden. |
| `base.digest` | string or null | The key is required. A `sha256:` value pins the base; `null` or a blank YAML value tracks `base.image` by tag. |
| `build_args` | mapping | Arbitrary non-secret scalar values passed to matching Dockerfile `ARG` declarations. Secret-like keys are rejected. |
| `mirror` | enum | Optional shared-capability setting: `upstream` or explicitly selected `aliyun`. |
| `runtime.ssh.mode` | enum | Optional shared-capability setting: `disabled`, `key-only`, or `password`; rendered as `SSH_MODE` when present. |
| `dependencies` | list | Internal targets exposed as named BuildKit contexts. |
| `tests` | list | One or more existing repository-relative smoke-test scripts. |

Each dependency contains `family`, `variant`, and `context`. The context name must be unique inside
the consumer variant and must match a Dockerfile named context:

```yaml
dependencies:
  - context: internal_base
    family: base
    variant: ubuntu-24.04
```

```dockerfile
FROM internal_base AS development
```

Buildx Bake resolves `internal_base` to `target:<generated-base-target>`, so a pull request never
uses an older registry copy for an internal dependency.

For an external base, a digest value renders `BASE_IMAGE` as `image:tag@sha256:...`; `null` renders
it as `image:tag`. YAML `digest: null` and `digest:` are equivalent, but omitting the key is invalid
so the reproducibility choice is always explicit. Development images use `digest: null` to receive
updates published under the same exact tag; a `sha256` pin remains available when a fixed base is
needed. Generated Bake targets check for updates with `pull: true`. Two builds of the same Git
commit can differ, so CI assigns each build batch its own immutable release tag. Exact version
tags remain required, and `latest` and `master` remain forbidden.

`build_args` is the extension point for image-specific build options and does not require a Python
parser change. Values are normalized to strings before Bake rendering. Scripts that accept boolean
options must therefore normalize YAML values such as `true` becoming `True`; environment-variable
expressions such as `${NAME}` are not interpolated and remain literal strings. Unknown fields
outside `build_args` remain forbidden by the schema.

`mirror` is different from a free-form build argument: the planner validates the enum and renders
it as `PACKAGE_MIRROR`. The Dockerfile passes that value to its final mirror capability. That script
owns the supported values: `upstream` leaves the base sources unchanged, while `aliyun` rewrites the
persisted apt and pip configuration after all package installation. No runtime mirror probe occurs.

`runtime.ssh.mode` is a typed runtime policy rather than a free-form build argument. Consumers can require it explicitly as a policy. The
planner renders it as the internal `SSH_MODE` build argument. The Dockerfile and entrypoint derive
the only permitted SSH account from `DEFAULT_USER`; there is no separate login-user selector.

## Complete shape

```yaml
schema_version: 1
name: example
description: Example development image
dockerfile: src/example/Dockerfile
context: .
platforms: [linux/amd64]
inputs:
  - src/example/**
  - vendor/image-kit/scripts/dev/example-tool.sh
publish: true
variants:
  - id: ubuntu-24.04
    base:
      image: ubuntu:24.04
      digest: sha256:<64-lowercase-hex-characters>
    build_args:
      DEFAULT_USER: developer
      DEFAULT_UID: 1000
      DEFAULT_GID: 1000
      WORKSPACE_DIR: /workspace
      TOOL_VERSION: "1.2.3"
    mirror: upstream
    runtime:
      ssh:
        mode: disabled
    dependencies: []
    tests:
      - src/example/tests/smoke.sh
```

To track an exact tag instead, retain the key and set it explicitly to null (or leave its YAML
value blank):

```yaml
base:
  image: ubuntu:24.04
  digest: null
```

The JSON Schema performs structural validation. `images validate` additionally checks paths,
directory/name equality, duplicate variants, secret-like build arguments, dependency targets, duplicate context names, smoke tests, and graph cycles. Account and bilingual documentation policies are checked by the consumer.

## Package and consumer policy

The authoritative schema is bundled as `image_kit/schemas/image.schema.json`; no local
`schemas/` directory is required. `mirror` and `runtime` are optional shared-capability fields.
Omitting them injects neither `PACKAGE_MIRROR` nor `SSH_MODE`. Image-specific account contracts,
required runtime settings, bilingual documentation, and publication permissions belong to each
consumer. This version supports the family/variant v1 contract and one native platform per family;
it does not automatically interpret other manifest formats.

The system capability accepts explicit `--timezone` and `--upgrade <true|false>` options. Upgrade defaults to false; consumers may pass a build argument to opt in without changing the component default.
