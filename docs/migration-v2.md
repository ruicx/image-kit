# Migrating to image-kit 0.2 and schema v2

This is an explicit breaking migration. Consumers pinned to older component commits retain
their old behavior. Upgrade consumers together with their manifests, checks, workflows, locked
dependencies, README/Compose references and direct-build defaults. Publish the component commit
before recording new consumer pins. CI must initialize reviewed pins recursively.

| Previous surface | v2 replacement |
| --- | --- |
| Family v1 and single-image v1 schemas | One packaged family/variant v2 schema. |
| Directory/name equality | Explicit YAML `name`; directories only locate files. |
| Single-image root base/build_args/smoke | One explicit version under `variants`; `tests` objects. |
| `base.dependency` or `dependencies` | Internal `base.target: name/variant` and `base.context`. |
| Bare test paths | Objects with script and optional helper, inputs, policy and entrypoint. |
| One platform per family | One or both supported platforms; parent covers child platforms. |
| `--image`, `--family ... --variant ...` | `--family <name>` or `--target <name/variant>`. |
| Format-specific plans and CLI implementations | One v2 plan, repository model and CLI. |
| `preflight`, `guard-tags`, `promote` | Digest-only native push, common `collect`/`merge`, and receipt-based `release`. |
| Automatic global aliases and Git-tag rebuilds | Explicit variant channels and promotion of verified build receipts. |

Luciole CUDA manifests use `pytorch26.06-py3`; this is the NVIDIA PyTorch image version, not
the CUDA toolkit version. Luciole Ascend uses its vendor-stack variant ID. utils/images retains
its existing variant IDs and all consumers retain package names. Luciole smoke tests explicitly
retain image entrypoints and helper-based assertion policy; utils tests retain a Bash override.

The migration directly switches publication rules. Old registry tags and artifacts are not
deleted, but subsequent builds do not maintain the old global aliases. Update active pulls,
Compose images and final-image base defaults to explicit variant channels. Historical
diagnostic documents may retain old references when clearly marked as past evidence.

Compare external base tags/digests, internal target edges, installation arguments, input lists,
platforms and smoke assertions before and after. Account, Dockerfile wiring and documentation
policies remain consumer-owned. Both consumers use locked local component dependencies and the
same CLI sequence, with a derived native worker matrix and a global tag-publication gate.
Version promotion is a separate manual workflow selecting the successful main run ID, attempt
and desired v-prefixed semantic version. It downloads that attempt's publication receipt,
checks the source workflow, and promotes existing registry digests without rebuilding.

Digest collection also checks that exported configs match the loaded smoke-test image IDs;
a changed second solve cannot advance public tags. Validation includes schema/model, planning,
native Bake, smoke invocation, artifact corruption,
immutable conflicts, provenance indexes and promotion tests; consumer policies; Ruff/ty; locked
installation; and wheel validation without local schemas or a submodule. Native image builds
and hardware tests remain separate requirements and must be reported independently.
