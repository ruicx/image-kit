# CLI and artifact contracts

Install the pinned component through the consumer's local uv source and run
`uv sync --locked --extra dev`. `images`, `image-kit` and `python -m image_kit` use the same
parser and implementation. Global `--root` selects the consumer root. Operational errors return
status 2; successful commands return 0. No Docker operation occurs during validation, planning
or Bake rendering.

| Command | Interface |
| --- | --- |
| `validate`, `list` | Validate all v2 contracts or list `name/variant` targets and platforms. |
| `files --kind shell` | List referenced scripts and configured shell inputs. |
| `plan` | Select `--all`, `--family <YAML-name>`, `--target <name/variant>`, or both `--base` and `--head`. Optional `--platform`, `--output`, `--github-output`. |
| `bake` | Require plan, owner, full revision, native platform and mode `load` or `publish`. Optional source repository, registry, build ID, output and `--github-cache`. |
| `test` | Require plan, owner, revision and platform; build ID must match the loaded images. |
| `build-test` | Same identity options plus `--bake`; validate the generated Bake file, build/test independent components and aggregate failures. |
| `collect` | Require plan, owner, revision, build ID, platform, metadata file and output file. Source repository and registry default to consumer settings. |
| `merge` | Require plan, owner, revision, build ID, digest directory, Git ref and output receipt. Optional `--dry-run`. |
| `release` | Require publication receipt, owner, revision, build ID and `--version vMAJOR.MINOR.PATCH`. Optional prerelease suffix, source/registry overrides and `--dry-run`. |

Explicit selection cannot be combined with a Git diff. Family and exact-target selection are
mutually exclusive. `--platform` filters selected outputs before ancestor expansion. Names are
read from YAML, never inferred from directories. Revision means a full forty-character Git SHA.

## Native plan and Bake

Plans contain `schema_version: 2`, `changed_files`, optional-filter `platform`, ordered `targets`
and `build_matrix.include`. A target records `name`, `variant`, normalized Bake `target`,
required `platforms`, `publish`, and `reason` (`selected` or `dependency`). Workers map amd64 to
`ubuntu-24.04` and arm64 to `ubuntu-24.04-arm`. No QEMU is configured.

Before using a plan, the engine reconstructs it from current manifests and rejects missing
ancestors, changed platforms or edited publication flags. `build-test` also compares the Bake
file with the current plan and identity before invoking Docker.

`bake --platform ... --mode load` loads one native architecture. It imports caches only when
explicitly requested and never exports them. `publish` requires `--build-id`, pushes selected
targets by digest and keeps ancestors cache-only. Cache scopes include target and architecture.
Direct CLI use of Actions cache needs the runtime variables exposed as described in
[Docker's cache documentation](https://docs.docker.com/build/cache/backends/gha/).

## Tags and release identity

For each explicit variant, the engine uses:

| Purpose | Tag | Policy |
| --- | --- | --- |
| Environment channel | `<variant>` | Advance only after a successful main publication. |
| Verified build | `<variant>-<sha12>-<run-id>-<attempt>` | Never overwrite with different content. |
| Formal version | `<variant>-v1.2.0` | Promote an existing verified main build; never rebuild or overwrite. |
| Local load/test | `<variant>-<sha12>-local` | Local only; not accepted for publication. |

Run ID and attempt are positive integers. Generated tags must fit Docker's 128-character limit.
No global `latest`, `main`, bare SHA or unprefixed release tag is generated. Platform variants
share a final manifest index; public tags do not add architecture suffixes. Registry mutations
across multiple tags are sequential, not transactional. Pin a final index digest for fixed use.

## Artifacts and promotion

Before collection, the CLI compares each exported `containerimage.config.digest` with the
Docker config ID of its loaded smoke-test image. A missing or changed image fails the worker,
preventing a second solve from publishing different runtime content under a verified tag.

Native digest artifacts have `schema_version: 2`, `kind: native-digests`, an `identity`, and
`digests`. Identity records registry, owner, source repository, full revision and build ID.
Each digest record has name, variant, platform and exporter digest. Metadata must be loaded
through files/stdin, never full provenance in environment variables or command arguments.

Merge rejects missing, duplicate, unexpected and mixed-identity records before registry writes.
It uses registry-side dry-run composition to account for nested BuildKit indexes and
attestations, validates exactly the planned runnable platforms, then preflights all existing
build tags. Explicit not-found responses are distinguished from authentication/network errors.
Matching immutable tags are skipped; conflicts fail. All build tags must succeed before any
floating environment tag advances.

After success, `merge --output publication.json` writes a receipt with kind `publication`, the
same identity, source Git ref and targets containing name, variant, build tag, platform list and
final index digest. Dry runs print intended writes and produce no success receipt.

`release` requires a matching main receipt. It verifies source build tags still match the
recorded digests and platforms and preflights every requested version tag before mutation.
Identical retries skip existing versions; conflicts fail. It neither moves environment channels
nor creates Git tags. Workflow callers additionally verify the source run, attempt, repository,
conclusion and publication workflow before trusting its downloaded artifact. Receipts are
retained for 90 days in the consumer workflows; retain a copy for later manual promotion.
