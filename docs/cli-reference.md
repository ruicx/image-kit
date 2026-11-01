# CLI reference

Run commands as `images ...` after installation or as `python -m image_kit ...`. The global
`--root` option selects a repository root and defaults to the current directory. Successful
commands return `0`; repository, Docker, or subprocess failures return `2` with an actionable
message on standard error.

| Command | Purpose | Important options/output |
| --- | --- | --- |
| `validate` | Validate manifests, paths, and DAG using image-kit's packaged schema. | No output file. |
| `list` | List families, variants, base-resolution modes, and direct dependencies. | Human-readable stdout; base mode is `pinned` or `tag-tracking`. |
| `files --kind shell` | List ShellCheck/shfmt inputs. | Repository-relative paths. |
| `plan` | Calculate publish targets and required ancestors. | Use `--base/--head`, `--all`, or `--family [--variant]`; optional `--platform` and `--output`. |
| `bake` | Render a JSON Bake definition from a plan. | Requires owner, revision, mode, and plan. Modes: `load`, `preflight`, `publish`. |
| `test` | Run declared smoke tests against locally loaded images. | Requires plan, owner, and revision. |
| `build-test` | Build and test every independent graph component. | Requires plan and generated Bake file; reports all failed components. |
| `guard-tags` | Compare local metadata with immutable registry tags. | Writes a filtered publication plan; conflicts fail. |
| `promote` | Move each floating variant tag to its immutable release. | Runs only after immutable publication succeeds. |

`plan --platform linux/arm64` filters selected outputs before adding their required ancestors.
Internal dependency edges must stay on the same platform. A platform with no selected targets
produces an empty plan.

`plan` emits schema version `1`, changed paths, and topologically ordered targets. A target's
`publish` flag distinguishes affected outputs from ancestors that are built only to satisfy the
DAG. Generated plan and Bake files are ephemeral CI artifacts and must not be edited by hand.

`bake --mode load` loads images into the local Docker daemon and includes floating tags for smoke
tests. `preflight` builds without pushing and produces digest metadata. `publish` pushes only
targets whose plan record still has `publish: true` and writes the scoped main-branch cache.
All generated targets set `pull: true` to check for upstream base updates while retaining layer caches.

`bake`, `test`, `build-test`, `guard-tags`, and `promote` accept optional `--build-id <run-id>-<attempt>`.
Both parts must be positive integers. CI passes `${{ github.run_id }}-${{ github.run_attempt }}`
consistently to every stage, generating `<variant>-<12-character-git-sha>-<run-id>-<attempt>` tags.
Local callers may omit the option to retain the existing `<variant>-<12-character-git-sha>` format,
or pass a unique numeric batch such as `--build-id "$(date +%s)-1"` to every stage of a rebuild.
The OCI revision label always remains the full source SHA.

Use `images <command> --help` as the authoritative option list. The command names, plan schema,
and exit-status meanings are compatibility-sensitive interfaces.

Registry commands accept `--registry`; the default is `ghcr.io`, overridable through
`[tool.image-kit].registry`. `bake --repository` accepts a full source URL or a GitHub
`owner/repository` shorthand. No source label is invented when this option is absent.
GitHub Actions caching is enabled only with `[tool.image-kit].cache = "gha"`.
`validate` does not impose a consumer documentation or Linux account policy.
