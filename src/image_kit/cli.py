"""One interface for v2 planning, native verification and publication."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .publication import (
    DIGEST,
    BuildIdentity,
    collect,
    image_config_digest,
    merge,
    release,
)
from .repository import (
    PLATFORMS,
    ImageRepository,
    RepositoryError,
    load_json,
    owner_name,
    registry_name,
    release_suffix,
    write_json,
)


def parser() -> argparse.ArgumentParser:
    """Build the shared parser.

    Returns
    -------
    argparse.ArgumentParser
        Common command parser.
    """
    result = argparse.ArgumentParser(prog="images")
    result.add_argument("--root", type=Path, default=Path.cwd())
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("list")
    files = commands.add_parser("files")
    files.add_argument("--kind", choices=["shell"], required=True)
    plan = commands.add_parser("plan")
    selection = plan.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--family")
    selection.add_argument("--target")
    plan.add_argument("--base")
    plan.add_argument("--head")
    plan.add_argument("--platform", choices=PLATFORMS)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--github-output", type=Path)
    for name in ("bake", "test", "build-test", "collect", "merge", "release"):
        command = commands.add_parser(name)
        command.add_argument("--owner", required=True, type=owner_name)
        command.add_argument("--registry", type=registry_name)
        command.add_argument("--repository", help="source repository override")
        command.add_argument("--revision", required=True)
        command.add_argument("--build-id")
        if name != "release":
            command.add_argument("--plan", required=True, type=Path)
        if name not in ("merge", "release"):
            command.add_argument("--platform", required=True, choices=PLATFORMS)
            command.add_argument("--component", help="generated native component ID")
        if name in ("bake", "build-test"):
            command.add_argument("--github-cache", action="store_true")
        if name == "bake":
            command.add_argument("--mode", required=True, choices=["load", "publish"])
            command.add_argument("--output", type=Path)
        if name == "build-test":
            command.add_argument("--bake", required=True, type=Path)
        if name == "collect":
            command.add_argument("--metadata", required=True, type=Path)
            command.add_argument("--output", required=True, type=Path)
        if name == "merge":
            command.add_argument("--digests", required=True, type=Path)
            command.add_argument("--ref", required=True)
            command.add_argument("--output", required=True, type=Path)
        if name == "release":
            command.add_argument("--publication", required=True, type=Path)
            command.add_argument("--version", required=True)
        if name in ("merge", "release"):
            command.add_argument("--dry-run", action="store_true")
    return result


def _run_tests(
    repo: ImageRepository, args: argparse.Namespace, plan: Mapping[str, Any]
) -> None:
    """Run native contracts and aggregate failures.

    Parameters
    ----------
    repo:
        Loaded repository.
    args:
        Native platform and image identity.
    plan:
        Validated plan or internally selected component.

    Raises
    ------
    RepositoryError
        If Docker or a required smoke test fails.
    """
    suffix = release_suffix(args.revision, args.build_id)
    failed: list[str] = []
    for item in plan["targets"]:
        if args.platform not in item["platforms"]:
            continue
        variant = repo.variants[(item["name"], item["variant"])]
        image = (
            f"{args.registry}/{args.owner}/{item['name']}:{item['variant']}-{suffix}"
        )
        for test in variant.tests:
            script = repo.path(test.script)
            command = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--env",
                f"SMOKE_HARD_GATE={'1' if test.policy == 'required' else '0'}",
                "--mount",
                f"type=bind,source={script.parent},target=/tmp/smoke,readonly",
            ]
            source = f"source {shlex.quote('/tmp/smoke/' + script.name)}"
            if test.library:
                source = (
                    f"source {shlex.quote('/tmp/smoke/' + Path(test.library).name)}"
                    f" && {source}"
                )
            if test.entrypoint == "bash":
                command.extend(["--entrypoint", "/bin/bash", image, "-c", source])
            else:
                command.extend([image, "bash", "-lc", source])
            print(
                f"Testing {item['name']}/{item['variant']} "
                f"on {args.platform}: {test.script}",
                flush=True,
            )
            if subprocess.run(command, check=False).returncode:
                failed.append(f"{item['name']}/{item['variant']}:{test.script}")
    if failed:
        raise RepositoryError(f"smoke execution failed: {', '.join(failed)}")


def _build_test(
    repo: ImageRepository, args: argparse.Namespace, plan: Mapping[str, Any]
) -> None:
    """Validate and build independent components, retaining diagnostics after failures.

    Parameters
    ----------
    repo:
        Loaded repository.
    args:
        Native identity and Bake file.
    plan:
        Complete validated plan.

    Raises
    ------
    RepositoryError
        If the Bake file differs or a component fails.
    """
    bake = load_json(args.bake)
    expected = repo.render_bake(
        plan,
        args.owner,
        args.revision,
        "load",
        args.repository,
        args.build_id,
        args.registry,
        platform=args.platform,
        github_cache=args.github_cache,
        component=args.component,
    )
    if bake != expected:
        raise RepositoryError(
            "Bake file does not match the current plan and worker identity"
        )
    failures: list[str] = []
    for group, value in bake["group"].items():
        if not group.startswith("component-"):
            continue
        try:
            subprocess.run(
                ["docker", "buildx", "bake", "--file", str(args.bake), group],
                check=True,
            )
            component_plan = {
                **plan,
                "targets": [
                    item
                    for item in plan["targets"]
                    if item["target"] in value["targets"]
                ],
            }
            _run_tests(repo, args, component_plan)
        except (subprocess.CalledProcessError, RepositoryError):
            failures.append(group)
    if failures:
        raise RepositoryError(f"build or smoke tests failed for: {', '.join(failures)}")


def _verify_tested_images(
    plan: Mapping[str, Any],
    metadata: Mapping[str, Any],
    identity: BuildIdentity,
    platform: str,
) -> None:
    """Require exported images to match the native images loaded for smoke tests.

    Parameters
    ----------
    plan:
        Validated complete plan.
    metadata:
        Digest-export Bake metadata.
    identity:
        Shared native build identity.
    platform:
        Native worker platform.

    Raises
    ------
    RepositoryError
        If publication re-solving changed a tested image or metadata is incomplete.
    subprocess.CalledProcessError
        If a tested image is no longer available locally.
    """
    identity.validate()
    suffix = release_suffix(identity.revision, identity.build_id)
    for item in plan["targets"]:
        if not item["publish"] or platform not in item["platforms"]:
            continue
        digest = metadata.get(item["target"], {}).get("containerimage.digest", "")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise RepositoryError(
                f"missing or invalid digest metadata: {item['target']}"
            )
        reference = identity.image(item["name"], f"{item['variant']}-{suffix}")
        config = image_config_digest(
            f"{reference.rsplit(':', 1)[0]}@{digest}", platform
        )
        tested = subprocess.check_output(
            ["docker", "image", "inspect", reference, "--format", "{{.Id}}"], text=True
        ).strip()
        if config != tested:
            raise RepositoryError(
                f"publication image differs from the tested image: {reference}"
            )


def run(arguments: Sequence[str] | None = None) -> int:
    """Execute one command using the shared repository model.

    Parameters
    ----------
    arguments:
        Optional arguments; None uses sys.argv.

    Returns
    -------
    int
        Zero on success.

    Raises
    ------
    RepositoryError
        If build or publication contracts are invalid.
    subprocess.CalledProcessError
        If a Git or Docker operation fails.
    """
    args = parser().parse_args(arguments)
    repo = ImageRepository(args.root)
    if hasattr(args, "registry"):
        args.registry = args.registry or repo.registry
        args.repository = args.repository or repo.source_repository
        args.revision = args.revision.lower()
        release_suffix(args.revision, args.build_id)
    if args.command == "release":
        identity = BuildIdentity(
            args.registry,
            args.owner,
            args.repository or "",
            args.revision,
            args.build_id,
        )
        release(
            load_json(args.publication), identity, args.version, dry_run=args.dry_run
        )
        return 0
    repo.load()
    if args.command == "validate":
        print(
            f"Validated {len(repo.families)} images "
            f"and {len(repo.variants)} variants (schema v2)"
        )
    elif args.command == "list":
        for key in repo.topological_order():
            print(f"{key[0]}/{key[1]} ({', '.join(repo.families[key[0]].platforms)})")
    elif args.command == "files":
        for path in repo.shell_files():
            print(path.relative_to(repo.root).as_posix())
    elif args.command == "plan":
        changed: list[str] = []
        if args.all or args.family or args.target:
            if args.base or args.head:
                raise RepositoryError(
                    "explicit selection cannot be combined with --base/--head"
                )
            selected = repo.select(args.family, args.target)
        elif args.base and args.head:
            changed = repo.changed_files(args.base, args.head)
            selected = repo.affected(changed)
        else:
            raise RepositoryError(
                "plan requires --all, --family, --target, or both --base and --head"
            )
        plan = repo.make_plan(selected, changed, args.platform)
        write_json(plan, args.output)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"has_build={'true' if plan['targets'] else 'false'}\n")
                output.write(f"build_matrix={json.dumps(plan['build_matrix'])}\n")
    else:
        plan = load_json(args.plan)
        repo.check_plan(plan)
        if args.command == "bake":
            write_json(
                repo.render_bake(
                    plan,
                    args.owner,
                    args.revision,
                    args.mode,
                    args.repository,
                    args.build_id,
                    args.registry,
                    platform=args.platform,
                    github_cache=args.github_cache,
                    component=args.component,
                ),
                args.output,
            )
        elif args.command == "test":
            _run_tests(
                repo,
                args,
                {
                    **plan,
                    "targets": repo.worker_targets(plan, args.platform, args.component),
                },
            )
        elif args.command == "build-test":
            _build_test(repo, args, plan)
        else:
            identity = BuildIdentity(
                args.registry,
                args.owner,
                args.repository or "",
                args.revision,
                args.build_id,
            )
            if args.command == "collect":
                plan = {
                    **plan,
                    "targets": repo.worker_targets(plan, args.platform, args.component),
                }
                metadata = load_json(args.metadata)
                _verify_tested_images(plan, metadata, identity, args.platform)
                write_json(
                    collect(plan, metadata, identity, args.platform), args.output
                )
            elif args.command == "merge":
                receipt = merge(
                    plan,
                    [load_json(path) for path in sorted(args.digests.glob("*.json"))],
                    identity,
                    args.ref,
                    dry_run=args.dry_run,
                )
                if receipt is not None:
                    write_json(receipt, args.output)
    return 0


def main() -> int:
    """Translate operational failures into command exit status two.

    Returns
    -------
    int
        Zero on success or two for an operational error.
    """
    try:
        return run()
    except (
        RepositoryError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
        yaml.YAMLError,
    ) as error:
        print(f"images: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
