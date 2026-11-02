"""Verify unified names, platform planning, smoke execution and CLI contracts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from image_kit.cli import run
from image_kit.repository import ImageRepository, RepositoryError


@pytest.fixture
def consumer(tmp_path: Path) -> ImageRepository:
    """Create renamed directories with a multi-platform parent and ARM64 child.

    Parameters
    ----------
    tmp_path:
        Temporary consumer root.

    Returns
    -------
    ImageRepository
        Validated v2 consumer.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[tool.image-kit]\nsource-repository="example/images"\n', encoding="utf-8"
    )
    (tmp_path / "common.sh").write_text("true\n", encoding="utf-8")
    for directory, name, parent in [
        ("core", "base", None),
        ("product", "app", "base/stack"),
    ]:
        folder = tmp_path / "src" / directory
        folder.mkdir(parents=True)
        (folder / "Dockerfile").write_text(
            "ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n", encoding="utf-8"
        )
        (folder / "smoke.sh").write_text("true\n", encoding="utf-8")
        (folder / "helpers.sh").write_text("true\n", encoding="utf-8")
        test: dict[str, Any] = {"script": f"src/{directory}/smoke.sh"}
        if parent is None:
            test.update(
                library=f"src/{directory}/helpers.sh",
                inputs=[f"src/{directory}/helpers.sh"],
                policy="advisory",
                entrypoint="image",
            )
        base = (
            {"target": parent, "context": "parent_image"}
            if parent
            else {"image": "ubuntu:24.04", "digest": None}
        )
        manifest = {
            "schema_version": 2,
            "name": name,
            "description": name,
            "context": ".",
            "dockerfile": f"src/{directory}/Dockerfile",
            "platforms": ["linux/arm64"] if parent else ["linux/amd64", "linux/arm64"],
            "inputs": ["common.sh"],
            "publish": True,
            "variants": [
                {"id": "stack", "base": base, "build_args": {}, "tests": [test]}
            ],
        }
        (folder / "image.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return ImageRepository(tmp_path).load()


def edit(consumer: ImageRepository, directory: str, transform: Any) -> None:
    """Mutate a fixture manifest and reload semantic validation.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    directory:
        Physical directory, independent of published name.
    transform:
        Manifest mutation callback.
    """
    path = consumer.root / "src" / directory / "image.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    transform(raw)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    consumer.load()


def test_yaml_name_controls_identity_after_directory_move(
    consumer: ImageRepository,
) -> None:
    """Preserve target identity and registry references across directory changes.

    Parameters
    ----------
    consumer:
        Consumer with names independent of directories.
    """
    assert set(consumer.families) == {"base", "app"}
    folder = consumer.root / "src/product"
    moved = consumer.root / "src/renamed"
    folder.rename(moved)
    path = moved / "image.yml"
    path.write_text(
        path.read_text().replace("src/product/", "src/renamed/"), encoding="utf-8"
    )
    consumer.load()
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    assert [item["name"] for item in plan["targets"]] == ["base", "app"]
    assert all(item["platforms"] == ["linux/arm64"] for item in plan["targets"])
    assert plan["targets"][0]["publish"] is False
    bake = consumer.render_bake(
        plan, "example", "a" * 40, "load", platform="linux/arm64"
    )
    app = bake["target"]["app--stack"]
    assert app["tags"] == ["ghcr.io/example/app:stack-aaaaaaaaaaaa-local"]
    assert app["contexts"] == {"parent_image": "target:base--stack"}
    assert app["args"]["BASE_IMAGE"] == "parent_image"
    assert app["dockerfile"] == "src/renamed/Dockerfile"


@pytest.mark.parametrize(
    "paths, names",
    [
        (["README.md", "src/core/README_zh.md", "src/core/docker-compose.yml"], set()),
        (["src/core/Dockerfile"], {"base", "app"}),
        (["src/product/smoke.sh"], {"app"}),
        (["src/core/helpers.sh"], {"base", "app"}),
        (["common.sh"], {"base", "app"}),
    ],
)
def test_actual_inputs_determine_impact(
    consumer: ImageRepository, paths: list[str], names: set[str]
) -> None:
    """Use declared paths rather than published-name directory assumptions.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    paths:
        Changed paths.
    names:
        Expected downstream image names.
    """
    assert {key[0] for key in consumer.affected(paths)} == names


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_name",
        "reserved_arg",
        "unknown_parent",
        "mixed_base",
        "missing_helper",
        "advisory_without_helper",
    ],
)
def test_invalid_v2_contracts(consumer: ImageRepository, damage: str) -> None:
    """Reject malformed identities, dependencies and test contracts.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    damage:
        Invalid mutation.
    """
    with pytest.raises(RepositoryError):
        if damage == "duplicate_name":
            edit(consumer, "product", lambda raw: raw.update(name="base"))
        elif damage == "reserved_arg":
            edit(
                consumer,
                "product",
                lambda raw: raw["variants"][0]["build_args"].update(BASE_TAG="x"),
            )
        elif damage == "unknown_parent":
            edit(
                consumer,
                "product",
                lambda raw: raw["variants"][0]["base"].update(target="missing/stack"),
            )
        elif damage == "mixed_base":
            edit(
                consumer,
                "product",
                lambda raw: raw["variants"][0]["base"].update(
                    image="ubuntu:24.04", digest=None
                ),
            )
        elif damage == "missing_helper":
            edit(
                consumer,
                "product",
                lambda raw: raw["variants"][0]["tests"][0].update(
                    library="src/product/absent.sh"
                ),
            )
        else:
            edit(
                consumer,
                "product",
                lambda raw: raw["variants"][0]["tests"][0].update(policy="advisory"),
            )


def test_duplicate_yaml_and_v1_have_actionable_errors(
    consumer: ImageRepository,
) -> None:
    """Reject hidden overrides and explicitly identify the v1 migration requirement.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    """
    path = consumer.root / "src/product/image.yml"
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "name: other\n", encoding="utf-8")
    with pytest.raises(RepositoryError, match="unique text"):
        consumer.load()
    path.write_text(
        original.replace("schema_version: 2", "schema_version: 1"), encoding="utf-8"
    )
    with pytest.raises(RepositoryError, match="migrate schema_version"):
        consumer.load()


def test_stale_plan_cannot_drop_ancestor_or_platform(consumer: ImageRepository) -> None:
    """Reject edited generated artifacts before Docker can execute.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    """
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    plan["targets"].pop(0)
    with pytest.raises(RepositoryError, match="does not match"):
        consumer.check_plan(plan)
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    plan["targets"][0]["platforms"] = ["linux/amd64"]
    with pytest.raises(RepositoryError, match="does not match"):
        consumer.check_plan(plan)


def test_cli_identity_smoke_and_docker_errors(
    consumer: ImageRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use common CLI identity while preserving entrypoints and fatal Docker errors.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    monkeypatch:
        Docker subprocess replacement.
    """
    path = consumer.root / "plan.json"
    run(
        [
            "--root",
            str(consumer.root),
            "plan",
            "--target",
            "app/stack",
            "--output",
            str(path),
        ]
    )
    calls: list[list[str]] = []

    def docker(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Capture Docker and simulate an advisory container startup failure.

        Parameters
        ----------
        command:
            Docker argument vector.
        **kwargs:
            Subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Exit code 125 for the base container.
        """
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 125 if "SMOKE_HARD_GATE=0" in command else 0
        )

    monkeypatch.setattr(subprocess, "run", docker)
    args = [
        "--root",
        str(consumer.root),
        "test",
        "--plan",
        str(path),
        "--owner",
        "example",
        "--revision",
        "a" * 40,
        "--build-id",
        "123-2",
        "--platform",
        "linux/arm64",
    ]
    with pytest.raises(RepositoryError, match="smoke execution failed"):
        run(args)
    assert len(calls) == 2
    assert "--entrypoint" not in calls[0]
    assert "--entrypoint" in calls[1]
    assert "--pull=never" in calls[0]
    assert "readonly" in calls[0][calls[0].index("--mount") + 1]
    assert "ghcr.io/example/app:stack-aaaaaaaaaaaa-123-2" in calls[1]


def test_publication_requires_build_identity_and_no_cache_exports_on_load(
    consumer: ImageRepository,
) -> None:
    """Prevent local tags from being published and keep cache permissions explicit.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    """
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    with pytest.raises(RepositoryError, match="build-id"):
        consumer.render_bake(
            plan, "example", "a" * 40, "publish", platform="linux/arm64"
        )
    local = consumer.render_bake(
        plan, "example", "a" * 40, "load", platform="linux/arm64"
    )
    assert all("cache-from" not in target for target in local["target"].values())
    cached = consumer.render_bake(
        plan, "example", "a" * 40, "load", platform="linux/arm64", github_cache=True
    )
    assert all("cache-to" not in target for target in cached["target"].values())
    published = consumer.render_bake(
        plan,
        "example",
        "a" * 40,
        "publish",
        build_id="123-2",
        platform="linux/arm64",
        github_cache=True,
    )
    assert published["target"]["base--stack"]["output"] == ["type=cacheonly"]
    assert "tags" not in published["target"]["app--stack"]


def test_build_test_rejects_edited_bake_before_docker(
    consumer: ImageRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent missing component groups from silently skipping build and smoke checks.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    monkeypatch:
        Docker replacement.
    """
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    path = consumer.root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    bake = consumer.root / "bake.json"
    bake.write_text('{"group": {}, "target": {}}', encoding="utf-8")
    calls: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RepositoryError, match="Bake file does not match"):
        run(
            [
                "--root",
                str(consumer.root),
                "build-test",
                "--plan",
                str(path),
                "--bake",
                str(bake),
                "--owner",
                "example",
                "--revision",
                "a" * 40,
                "--platform",
                "linux/arm64",
            ]
        )
    assert not calls


def test_build_test_continues_independent_graph_after_failure(
    consumer: ImageRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attempt unrelated graphs before reporting a native build failure.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    monkeypatch:
        Docker replacement.
    """
    folder = consumer.root / "src/independent"
    folder.mkdir()
    raw = yaml.safe_load(
        (consumer.root / "src/core/image.yml").read_text(encoding="utf-8")
    )
    raw["name"] = "other"
    (folder / "image.yml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    consumer.load()
    plan = consumer.make_plan(consumer.variants)
    path = consumer.root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    bake = consumer.root / "bake.json"
    bake.write_text(
        json.dumps(
            consumer.render_bake(
                plan, "example", "a" * 40, "load", platform="linux/arm64"
            )
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def docker(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Fail the first graph and permit later graph builds and smoke checks.

        Parameters
        ----------
        command:
            Docker command vector.
        **kwargs:
            Subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Successful later component result.

        Raises
        ------
        subprocess.CalledProcessError
            For the first independent graph.
        """
        calls.append(command)
        if command[1:3] == ["buildx", "bake"] and command[-1] == "component-0":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", docker)
    with pytest.raises(RepositoryError, match="component-0"):
        run(
            [
                "--root",
                str(consumer.root),
                "build-test",
                "--plan",
                str(path),
                "--bake",
                str(bake),
                "--owner",
                "example",
                "--revision",
                "a" * 40,
                "--platform",
                "linux/arm64",
            ]
        )
    assert any(command[-1] == "component-1" for command in calls)
    assert any(
        command[1] == "run" and any("/other:stack-" in part for part in command)
        for command in calls
    )


@pytest.mark.parametrize("config", ["sha256:" + "b" * 64, "sha256:" + "c" * 64, None])
def test_collect_accepts_only_the_tested_image(
    consumer: ImageRepository, monkeypatch: pytest.MonkeyPatch, config: str | None
) -> None:
    """Reject an export that changed after smoke tests before issuing native artifacts.

    Parameters
    ----------
    consumer:
        Consumer fixture.
    monkeypatch:
        Local Docker image inspection replacement.
    config:
        Exported config digest, or None for missing metadata.
    """
    plan = consumer.make_plan(consumer.select(target="app/stack"))
    path = consumer.root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    metadata = consumer.root / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "app--stack": {
                    "containerimage.digest": "sha256:" + "d" * 64,
                    "containerimage.config.digest": config,
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def inspect(command: list[str], **kwargs: Any) -> str:
        """Return the config ID of the loaded and tested native image.

        Parameters
        ----------
        command:
            Docker image inspection arguments.
        **kwargs:
            Subprocess options.

        Returns
        -------
        str
            Loaded config digest.
        """
        calls.append(command)
        assert command == [
            "docker",
            "image",
            "inspect",
            "ghcr.io/example/app:stack-aaaaaaaaaaaa-123-2",
            "--format",
            "{{.Id}}",
        ]
        return "sha256:" + "b" * 64 + "\n"

    monkeypatch.setattr(subprocess, "check_output", inspect)
    output = consumer.root / "digests.json"
    command = [
        "--root",
        str(consumer.root),
        "collect",
        "--plan",
        str(path),
        "--metadata",
        str(metadata),
        "--owner",
        "example",
        "--revision",
        "a" * 40,
        "--build-id",
        "123-2",
        "--platform",
        "linux/arm64",
        "--output",
        str(output),
    ]
    if config == "sha256:" + "b" * 64:
        assert run(command) == 0
        assert json.loads(output.read_text())["digests"][0]["name"] == "app"
        assert len(calls) == 1
    else:
        with pytest.raises(
            RepositoryError, match="differs from the tested|missing config digest"
        ):
            run(command)
        assert not output.exists()
