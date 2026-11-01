"""Command-line interface for repository validation, planning, and publication."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .repository import (
    ImageRepository,
    RepositoryError,
    load_json,
    registry_name,
    release_suffix,
    write_json,
)


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for the ``images`` command.
    """
    result = argparse.ArgumentParser(prog="images")
    result.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    subcommands = result.add_subparsers(dest="command", required=True)

    subcommands.add_parser("validate", help="validate all manifests and dependency edges")
    subcommands.add_parser("list", help="list image families and variants")
    files = subcommands.add_parser("files", help="list referenced files for repository checks")
    files.add_argument("--kind", choices=("shell",), required=True)

    plan = subcommands.add_parser("plan", help="calculate affected targets")
    plan.add_argument("--base")
    plan.add_argument("--head")
    plan.add_argument("--all", action="store_true")
    plan.add_argument("--family")
    plan.add_argument("--variant")
    plan.add_argument("--platform", choices=("linux/amd64", "linux/arm64"))
    plan.add_argument("--output", type=Path)

    bake = subcommands.add_parser("bake", help="render a Docker Buildx Bake file")
    bake.add_argument("--plan", type=Path, required=True)
    bake.add_argument("--owner", required=True)
    bake.add_argument("--revision", required=True)
    bake.add_argument("--repository", help="source repository URL or GitHub owner/repository")
    bake.add_argument("--mode", choices=("load", "preflight", "publish"), required=True)
    bake.add_argument("--output", type=Path)

    test = subcommands.add_parser("test", help="run manifest smoke tests against loaded images")
    test.add_argument("--plan", type=Path, required=True)
    test.add_argument("--owner", required=True)
    test.add_argument("--revision", required=True)

    build_test = subcommands.add_parser(
        "build-test", help="build and test every independent Bake component"
    )
    build_test.add_argument("--plan", type=Path, required=True)
    build_test.add_argument("--bake", type=Path, required=True)
    build_test.add_argument("--owner", required=True)
    build_test.add_argument("--revision", required=True)

    guard = subcommands.add_parser("guard-tags", help="reject conflicting immutable tags")
    guard.add_argument("--plan", type=Path, required=True)
    guard.add_argument("--metadata", type=Path, required=True)
    guard.add_argument("--owner", required=True)
    guard.add_argument("--revision", required=True)
    guard.add_argument("--output", type=Path, required=True)

    promote = subcommands.add_parser("promote", help="update floating tags from immutable tags")
    promote.add_argument("--plan", type=Path, required=True)
    promote.add_argument("--owner", required=True)
    promote.add_argument("--revision", required=True)
    for command in (bake, test, build_test, guard, promote):
        command.add_argument("--build-id", help="numeric run-id-attempt suffix for release tags")
        command.add_argument(
            "--registry", type=registry_name, help="override the configured registry"
        )
    return result


def _published_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return plan targets still marked for publication.

    Parameters
    ----------
    plan:
        Versioned build plan.

    Returns
    -------
    list[dict[str, Any]]
        Publishable target records.
    """
    return [item for item in plan["targets"] if item["publish"]]


def _remote_digest(reference: str) -> str | None:
    """Inspect a remote image reference without failing when it is absent.

    Parameters
    ----------
    reference:
        Fully qualified container image reference.

    Returns
    -------
    str or None
        Remote manifest digest, or ``None`` when inspection fails.
    """
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{.Manifest.Digest}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _guard_tags(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    """Filter existing matching tags and reject immutable tag conflicts.

    Parameters
    ----------
    args:
        Parsed ``guard-tags`` arguments.
    plan:
        Build plan to filter for publication.

    Raises
    ------
    RepositoryError
        If local digest metadata is missing or a remote digest conflicts.
    """
    metadata = load_json(args.metadata)
    suffix = release_suffix(args.revision, args.build_id)
    # Copy through JSON because plan records are intentionally JSON-compatible data.
    filtered = json.loads(json.dumps(plan))
    for item in filtered["targets"]:
        if not item["publish"]:
            continue
        reference = (
            f"{args.registry}/{args.owner.lower()}/{item['family']}:{item['variant']}-{suffix}"
        )
        remote = _remote_digest(reference)
        if remote is None:
            continue
        local = metadata.get(item["target"], {}).get("containerimage.digest")
        if not local:
            raise RepositoryError(f"missing local digest metadata for {item['target']}")
        if remote != local:
            raise RepositoryError(
                f"immutable tag conflict for {reference}: remote={remote}, local={local}"
            )
        item["publish"] = False
        print(f"immutable tag already exists with matching digest; skipping: {reference}")
    write_json(filtered, args.output)


def _promote(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    """Point floating variant tags at their immutable release tags.

    Parameters
    ----------
    args:
        Parsed ``promote`` arguments.
    plan:
        Successfully published build plan.
    """
    suffix = release_suffix(args.revision, args.build_id)
    for item in _published_items(plan):
        prefix = f"{args.registry}/{args.owner.lower()}/{item['family']}"
        immutable = f"{prefix}:{item['variant']}-{suffix}"
        floating = f"{prefix}:{item['variant']}"
        subprocess.run(
            ["docker", "buildx", "imagetools", "create", "--tag", floating, immutable],
            check=True,
        )


def _run_tests(repo: ImageRepository, args: argparse.Namespace, plan: dict[str, Any]) -> None:
    """Run manifest-declared smoke tests against locally loaded images.

    Parameters
    ----------
    repo:
        Loaded repository model.
    args:
        Parsed command arguments containing owner, revision, and build identifier.
    plan:
        Plan whose targets should be tested.
    """
    suffix = release_suffix(args.revision, args.build_id)
    for item in plan["targets"]:
        variant = repo.variants[(item["family"], item["variant"])]
        image = (
            f"{args.registry}/{args.owner.lower()}/{variant.family}:{variant.identifier}-{suffix}"
        )
        for script_name in variant.tests:
            script = repo.root / script_name
            print(f"testing {image} with {script_name}")
            subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "/bin/bash", image, "-s"],
                input=script.read_text(encoding="utf-8"),
                text=True,
                check=True,
            )


def _build_and_test_components(
    repo: ImageRepository, args: argparse.Namespace, plan: dict[str, Any]
) -> None:
    """Build and test every independent graph component.

    A failed component is recorded while unrelated components continue, which
    preserves diagnostic coverage for repositories with multiple image graphs.

    Parameters
    ----------
    repo:
        Loaded repository model.
    args:
        Parsed ``build-test`` arguments.
    plan:
        Complete build plan.

    Raises
    ------
    RepositoryError
        If one or more components fail to build or pass smoke tests.
    """
    bake = load_json(args.bake)
    groups = sorted(name for name in bake.get("group", {}) if name.startswith("component-"))
    failures: list[str] = []
    # Continue after a component failure to preserve diagnostics for unrelated graphs.
    for group in groups:
        target_names = set(bake["group"][group]["targets"])
        component_plan = dict(plan)
        component_plan["targets"] = [
            item for item in plan["targets"] if item["target"] in target_names
        ]
        print(f"building independent graph component: {group}")
        try:
            subprocess.run(
                ["docker", "buildx", "bake", "--file", str(args.bake), group],
                check=True,
            )
            _run_tests(repo, args, component_plan)
        except subprocess.CalledProcessError:
            failures.append(group)
    if failures:
        raise RepositoryError(f"build or smoke tests failed for: {', '.join(failures)}")


def run(arguments: Sequence[str] | None = None) -> int:
    """Execute one CLI command.

    Parameters
    ----------
    arguments:
        Optional argument sequence. ``None`` reads from ``sys.argv``.

    Returns
    -------
    int
        Zero when the command completes successfully.
    """
    args = parser().parse_args(arguments)
    repo = ImageRepository(args.root).load()
    if hasattr(args, "registry"):
        args.registry = args.registry or repo.registry
    if args.command == "validate":
        print(f"validated {len(repo.families)} families and {len(repo.variants)} variants")
    elif args.command == "list":
        for family in repo.families.values():
            print(f"{family.name}: {family.description}")
            for variant in family.variants:
                base_mode = "pinned" if variant.base_digest is not None else "tag-tracking"
                dependencies = (
                    ", ".join(f"{item.family}/{item.variant}" for item in variant.dependencies)
                    or "none"
                )
                print(f"  {variant.identifier} (base: {base_mode}, dependencies: {dependencies})")
    elif args.command == "files":
        for path in repo.shell_files():
            print(path.relative_to(repo.root).as_posix())
    elif args.command == "plan":
        if args.all or args.family:
            targets = repo.select(args.family, args.variant)
            changed: list[str] = []
        else:
            if not args.base or not args.head:
                raise RepositoryError(
                    "plan requires --base and --head unless --all/--family is used"
                )
            changed = repo.changed_files(args.base, args.head)
            targets = repo.affected(changed)
        if args.platform:
            targets = {key for key in targets if args.platform in repo.families[key[0]].platforms}
        write_json(repo.make_plan(targets, changed), args.output)
    elif args.command == "bake":
        plan = load_json(args.plan)
        write_json(
            repo.render_bake(
                plan,
                args.owner,
                args.revision,
                args.mode,
                source_repository=args.repository,
                build_id=args.build_id,
                registry=args.registry,
            ),
            args.output,
        )
    elif args.command == "test":
        _run_tests(repo, args, load_json(args.plan))
    elif args.command == "build-test":
        _build_and_test_components(repo, args, load_json(args.plan))
    elif args.command == "guard-tags":
        _guard_tags(args, load_json(args.plan))
    elif args.command == "promote":
        _promote(args, load_json(args.plan))
    return 0


def main() -> int:
    """Run the CLI with consistent user-facing error handling.

    Returns
    -------
    int
        Process exit status: zero on success and two on an operational error.
    """
    try:
        return run()
    except (RepositoryError, subprocess.CalledProcessError) as error:
        print(f"images: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
