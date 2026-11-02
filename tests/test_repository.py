"""Unit tests for manifest validation, graph planning, and Bake rendering."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from image_kit.cli import run
from image_kit.repository import ImageRepository, RepositoryError, release_suffix


def variant(identifier: str, dependencies: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Create a minimal schema-valid variant for repository tests.

    Parameters
    ----------
    identifier:
        Variant identifier.
    dependencies:
        Optional internal dependency records.

    Returns
    -------
    dict[str, Any]
        Mutable variant manifest data.
    """
    return {
        "id": identifier,
        "base": {
            "target": f"{dependencies[0]['family']}/{dependencies[0]['variant']}",
            "context": dependencies[0]["context"],
        }
        if dependencies
        else {"image": "ubuntu:24.04", "digest": "sha256:" + "a" * 64},
        "build_args": {},
        "mirror": "upstream",
        "runtime": {"ssh": {"mode": "disabled"}},
        "tests": [{"script": "src/demo/tests/smoke.sh"}],
    }


def manifest(name: str, variants: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a minimal family manifest for repository tests.

    Parameters
    ----------
    name:
        Family and directory name.
    variants:
        Variant records to include.

    Returns
    -------
    dict[str, Any]
        Mutable family manifest data.
    """
    return {
        "schema_version": 2,
        "name": name,
        "description": f"{name} image",
        "dockerfile": f"src/{name}/Dockerfile",
        "context": ".",
        "platforms": ["linux/amd64"],
        "inputs": [f"src/{name}/Dockerfile"],
        "publish": True,
        "variants": variants,
    }


def write_family(root: Path, name: str, data: dict[str, Any]) -> None:
    """Write a temporary image family and its required files.

    Parameters
    ----------
    root:
        Temporary repository root.
    name:
        Family directory name.
    data:
        Manifest mapping to serialize.
    """
    directory = root / "src" / name
    (directory / "tests").mkdir(parents=True)
    (directory / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (directory / "tests" / "smoke.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    for item in data["variants"]:
        item["tests"] = [{"script": f"src/{name}/tests/smoke.sh"}]
    (directory / "image.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Create a consumer repository with explicit rebuild input configuration.

    Parameters
    ----------
    tmp_path:
        Value used by this operation.

    Returns
    -------
    Path
        Create a consumer repository with explicit rebuild input configuration.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[tool.image-kit]\nrebuild-inputs = ["tools/**", ".gitmodules", "vendor/image-kit"]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_loads_valid_repository(repo_root: Path) -> None:
    """Load a repository whose manifest and files satisfy all contracts.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "demo", manifest("demo", [variant("24.04")]))
    repository = ImageRepository(repo_root).load()
    assert list(repository.families) == ["demo"]


def test_generic_repository_needs_no_local_schema_or_runtime_policy(tmp_path: Path) -> None:
    """Validate an unrelated checkout using only the schema bundled in the package.

    Parameters
    ----------
    tmp_path:
        Repository without this project's docs, submodule, or runtime settings.
    """
    item = variant("one")
    del item["runtime"]
    del item["mirror"]
    write_family(tmp_path, "demo", manifest("demo", [item]))
    assert not (tmp_path / "schemas").exists()
    assert run(["--root", str(tmp_path), "validate"]) == 0
    repository = ImageRepository(tmp_path).load()
    bake = repository.render_bake(
        repository.make_plan(repository.variants),
        "example",
        "1" * 40,
        "load",
        platform="linux/amd64",
    )
    target = next(iter(bake["target"].values()))
    assert "SSH_MODE" not in target["args"]
    assert "PACKAGE_MIRROR" not in target["args"]
    assert "cache-from" not in target
    assert "org.opencontainers.image.source" not in target["labels"]


def test_registry_and_cache_are_consumer_configuration(repo_root: Path) -> None:
    """Render registry and cache settings without changing engine code.

    Parameters
    ----------
    repo_root:
        Repository using a registry outside GitHub.
    """
    (repo_root / "pyproject.toml").write_text(
        '[tool.image-kit]\nregistry = "registry.example.com:5000"\ncache = "gha"\n',
        encoding="utf-8",
    )
    write_family(repo_root, "demo", manifest("demo", [variant("one")]))
    repository = ImageRepository(repo_root).load()
    bake = repository.render_bake(
        repository.make_plan(repository.variants),
        "example",
        "1" * 40,
        "publish",
        source_repository="https://git.example.com/team/images",
        platform="linux/amd64",
        build_id="123-1",
        github_cache=True,
    )
    target = next(iter(bake["target"].values()))
    assert "push-by-digest=true" in target["output"][0]
    assert "tags" not in target
    assert target["cache-to"] == ["type=gha,mode=max,scope=demo--one-amd64"]
    assert (
        target["labels"]["org.opencontainers.image.source"] == "https://git.example.com/team/images"
    )


@pytest.mark.parametrize("name", ["rebuild-inputs", "shell-inputs"])
def test_rejects_invalid_consumer_path_configuration(repo_root: Path, name: str) -> None:
    """Reject a scalar where the engine expects a list of input patterns.

    Parameters
    ----------
    repo_root:
        Consumer repository containing malformed tool settings.
    name:
        Path-list setting to validate.
    """
    (repo_root / "pyproject.toml").write_text(
        f'[tool.image-kit]\n{name} = "wrong-type"\n', encoding="utf-8"
    )
    with pytest.raises(RepositoryError, match="list of path patterns"):
        ImageRepository(repo_root)


@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
def test_platform_selection_preserves_build_dependencies(repo_root: Path, platform: str) -> None:
    """Filter publication by platform while retaining same-platform build ancestors.

    Parameters
    ----------
    repo_root:
        Temporary repository using the packaged schema.
    platform:
        Architecture selected for the native CI worker.
    """
    write_family(repo_root, "other", manifest("other", [variant("one")]))
    dependency = {"context": "internal_base", "family": "base", "variant": "one"}
    for name, dependencies in [("base", None), ("child", [dependency])]:
        data = manifest(name, [variant("one", dependencies)])
        data["platforms"] = ["linux/arm64"]
        write_family(repo_root, name, data)
    plan_path = repo_root / "plan.json"
    assert (
        run(
            [
                "--root",
                str(repo_root),
                "plan",
                "--all",
                "--platform",
                platform,
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    families = [item["name"] for item in plan["targets"]]
    assert families == (["base", "child"] if platform == "linux/arm64" else ["other"])
    repository = ImageRepository(repo_root).load()
    bake = repository.render_bake(plan, "example", "1" * 40, "load", platform=platform)
    assert all(target["platforms"] == [platform] for target in bake["target"].values())


def test_platform_plan_retains_unselected_ancestor(repo_root: Path) -> None:
    """Keep an ARM64 ancestor private when only its consumer is selected for publication.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    dependency = {"context": "base", "family": "base", "variant": "one"}
    for name, dependencies in [("base", None), ("child", [dependency])]:
        data = manifest(name, [variant("one", dependencies)])
        data["platforms"] = ["linux/arm64"]
        write_family(repo_root, name, data)
    plan_path = repo_root / "plan.json"
    run(
        [
            "--root",
            str(repo_root),
            "plan",
            "--family",
            "child",
            "--platform",
            "linux/arm64",
            "--output",
            str(plan_path),
        ]
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert [(item["name"], item["publish"]) for item in plan["targets"]] == [
        ("base", False),
        ("child", True),
    ]
    run(
        [
            "--root",
            str(repo_root),
            "plan",
            "--family",
            "child",
            "--platform",
            "linux/amd64",
            "--output",
            str(plan_path),
        ]
    )
    assert json.loads(plan_path.read_text(encoding="utf-8"))["targets"] == []


@pytest.mark.parametrize("platforms", [[], ["linux/ppc64le"], ["linux/amd64", "linux/amd64"]])
def test_rejects_unsupported_platform_sets(repo_root: Path, platforms: list[str]) -> None:
    """Reject platform sets that cannot use the native single-platform load workflow.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    platforms:
        Candidate platform list.
    """
    data = manifest("demo", [variant("one")])
    data["platforms"] = platforms
    write_family(repo_root, "demo", data)
    with pytest.raises(RepositoryError, match="platforms"):
        ImageRepository(repo_root).load()


def test_rejects_cross_platform_internal_dependencies(repo_root: Path) -> None:
    """Prevent architecture-filtered jobs from requiring a foreign-platform build ancestor.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "base", manifest("base", [variant("one")]))
    dependency = {"context": "base", "family": "base", "variant": "one"}
    data = manifest("child", [variant("one", [dependency])])
    data["platforms"] = ["linux/arm64"]
    write_family(repo_root, "child", data)
    with pytest.raises(RepositoryError, match="support its platforms"):
        ImageRepository(repo_root).load()


@pytest.mark.parametrize("blank_style", ["null", "empty"])
def test_accepts_explicitly_unpinned_base_digest(repo_root: Path, blank_style: str) -> None:
    """Accept both YAML spellings that explicitly select tag tracking.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    blank_style:
        YAML spelling of an explicit null digest.
    """
    item = variant("tracking")
    item["base"]["digest"] = None
    write_family(repo_root, "demo", manifest("demo", [item]))
    manifest_path = repo_root / "src" / "demo" / "image.yml"
    if blank_style == "empty":
        serialized = manifest_path.read_text(encoding="utf-8")
        manifest_path.write_text(serialized.replace("digest: null", "digest:"), encoding="utf-8")
    repository = ImageRepository(repo_root).load()
    loaded = repository.variants["demo", "tracking"]
    assert loaded.base_digest is None
    assert loaded.base_reference == "ubuntu:24.04"


def test_requires_base_digest_key(repo_root: Path) -> None:
    """Reject omission of the digest key even though its value may be null.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    item = variant("one")
    del item["base"]["digest"]
    write_family(repo_root, "demo", manifest("demo", [item]))
    with pytest.raises(RepositoryError, match="digest.*required"):
        ImageRepository(repo_root).load()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("id", "latest", "latest"), ("digest", "sha256:nope", "does not match")],
)
def test_schema_rejects_invalid_release_inputs(
    repo_root: Path, field: str, value: str, message: str
) -> None:
    """Reject release identifiers and digests that violate the JSON Schema.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    field:
        Manifest field being exercised.
    value:
        Invalid field value.
    message:
        Expected validation diagnostic.
    """
    item = variant("24.04")
    if field == "digest":
        item["base"][field] = value
    else:
        item[field] = value
    write_family(repo_root, "demo", manifest("demo", [item]))
    with pytest.raises(RepositoryError, match=message):
        ImageRepository(repo_root).load()


def test_requires_explicit_base_tag(repo_root: Path) -> None:
    """Reject an external base image without an explicit version tag.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    item = variant("one")
    item["base"]["image"] = "ubuntu"
    write_family(repo_root, "demo", manifest("demo", [item]))
    with pytest.raises(RepositoryError, match="explicit version tag"):
        ImageRepository(repo_root).load()


def test_rejects_secret_like_build_arguments(repo_root: Path) -> None:
    """Reject build-argument keys that appear to contain secrets.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    item = variant("one")
    item["build_args"] = {"API_TOKEN": "must-not-be-here"}
    write_family(repo_root, "demo", manifest("demo", [item]))
    with pytest.raises(RepositoryError, match="secret-like keys"):
        ImageRepository(repo_root).load()


def test_accepts_custom_default_user_and_renders_ssh_mode(repo_root: Path) -> None:
    """Accept a named default user and pass its explicit SSH mode to Bake.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    item = variant("one")
    item["build_args"] = {
        "DEFAULT_USER": "builder",
        "DEFAULT_UID": 1001,
        "DEFAULT_GID": 1001,
        "DEFAULT_GROUPS": "video,render",
    }
    item["runtime"]["ssh"]["mode"] = "password"
    write_family(repo_root, "demo", manifest("demo", [item]))
    repository = ImageRepository(repo_root).load()
    plan = repository.make_plan({("demo", "one")})
    bake = repository.render_bake(plan, "example", "1" * 40, "load", platform="linux/amd64")
    target = next(iter(bake["target"].values()))
    assert target["args"]["DEFAULT_USER"] == "builder"
    assert target["args"]["DEFAULT_GROUPS"] == "video,render"
    assert target["args"]["SSH_MODE"] == "password"
    assert "SSH_LOGIN_USER" not in target["args"]


def test_rejects_duplicate_variant(repo_root: Path) -> None:
    """Reject duplicate variant identifiers within one family.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "demo", manifest("demo", [variant("one"), variant("one")]))
    with pytest.raises(RepositoryError, match="duplicate variant"):
        ImageRepository(repo_root).load()


def test_rejects_unknown_dependency(repo_root: Path) -> None:
    """Reject an internal dependency that does not identify a known target.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    dependency = {"context": "base", "family": "missing", "variant": "one"}
    write_family(repo_root, "demo", manifest("demo", [variant("one", [dependency])]))
    with pytest.raises(RepositoryError, match="unknown target missing/one"):
        ImageRepository(repo_root).load()


def test_rejects_dependency_cycle(repo_root: Path) -> None:
    """Reject a dependency graph containing a cycle.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    one_dep = {"context": "two", "family": "demo", "variant": "two"}
    two_dep = {"context": "one", "family": "demo", "variant": "one"}
    write_family(
        repo_root, "demo", manifest("demo", [variant("one", [one_dep]), variant("two", [two_dep])])
    )
    with pytest.raises(RepositoryError, match="contains a cycle"):
        ImageRepository(repo_root).load()


def test_change_propagates_to_dependents_and_bake_uses_target_context(repo_root: Path) -> None:
    """Propagate base changes and connect consumers to same-build targets.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "base", manifest("base", [variant("one")]))
    dependency = {"context": "internal_base", "family": "base", "variant": "one"}
    child = manifest("child", [variant("one", [dependency])])
    child["variants"][0]["tests"] = ["src/child/tests/smoke.sh"]
    write_family(repo_root, "child", child)
    repository = ImageRepository(repo_root).load()
    affected = repository.affected(["src/base/Dockerfile"])
    assert affected == {("base", "one"), ("child", "one")}
    plan = repository.make_plan(affected)
    bake = repository.render_bake(plan, "Example", "1" * 40, "load", platform="linux/amd64")
    child_target = repository.variants["child", "one"].target_name
    base_target = repository.variants["base", "one"].target_name
    assert bake["target"][child_target]["contexts"]["internal_base"] == f"target:{base_target}"


def test_tags_use_family_variant_and_short_revision(repo_root: Path) -> None:
    """Generate immutable and floating tags from the release contract.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "demo", manifest("demo", [variant("24.04")]))
    repository = ImageRepository(repo_root).load()
    plan = repository.make_plan({("demo", "24.04")})
    bake = repository.render_bake(
        plan, "Example", "abcdef012345" + "0" * 28, "load", platform="linux/amd64"
    )
    target = next(iter(bake["target"].values()))
    assert target["tags"] == ["ghcr.io/example/demo:24.04-abcdef012345-local"]
    assert target["args"]["BASE_IMAGE"] == "ubuntu:24.04@sha256:" + "a" * 64


def test_bake_tracks_base_tag_when_digest_is_null(repo_root: Path) -> None:
    """Pass only the exact base tag to BuildKit for an unpinned variant.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    item = variant("tracking")
    item["base"]["digest"] = None
    write_family(repo_root, "demo", manifest("demo", [item]))
    repository = ImageRepository(repo_root).load()
    plan = repository.make_plan({("demo", "tracking")})
    bake = repository.render_bake(plan, "example", "1" * 40, "load", platform="linux/amd64")
    target = next(iter(bake["target"].values()))
    assert target["args"]["BASE_IMAGE"] == "ubuntu:24.04"
    assert target["pull"] is True


@pytest.mark.parametrize("mode", ["load", "publish"])
def test_rebuilds_have_distinct_tags_and_preserve_revision(repo_root: Path, mode: str) -> None:
    """Distinguish workflow runs and attempts while preserving source attribution.

    Parameters
    ----------
    repo_root:
        Temporary repository using the packaged schema.
    mode:
        Build stage whose tags and labels must match the release contract.
    """
    write_family(repo_root, "demo", manifest("demo", [variant("24.04")]))
    repository = ImageRepository(repo_root).load()
    plan = repository.make_plan({("demo", "24.04")})
    revision = "abcdef012345" + "0" * 28
    tags = []
    for build_id in ("123-1", "123-2", "124-1"):
        bake = repository.render_bake(
            plan, "Example", revision, mode, build_id=build_id, platform="linux/amd64"
        )
        target = next(iter(bake["target"].values()))
        version = f"24.04-abcdef012345-{build_id}"
        if mode == "load":
            assert target["tags"][0] == f"ghcr.io/example/demo:{version}"
        else:
            assert "tags" not in target
        assert target["labels"]["org.opencontainers.image.revision"] == revision
        assert target["labels"]["org.opencontainers.image.version"] == version
        assert target["args"]["IMAGE_VERSION"] == version
        assert target["pull"] is True
        tags.append(version)
    assert len(set(tags)) == 3


@pytest.mark.parametrize("build_id", ["", "123", "0-1", "123-0", "123/1", "123-1:bad"])
def test_rejects_invalid_build_identifier(build_id: str) -> None:
    """Reject identifiers that cannot represent a workflow run and attempt.

    Parameters
    ----------
    build_id:
        Invalid release batch identifier.
    """
    with pytest.raises(RepositoryError, match="build-id"):
        release_suffix("1" * 40, build_id)


def test_independent_graph_branches_get_separate_bake_groups(repo_root: Path) -> None:
    """Place disconnected image graphs in independent Bake groups.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "one", manifest("one", [variant("base")]))
    write_family(repo_root, "two", manifest("two", [variant("base")]))
    repository = ImageRepository(repo_root).load()
    plan = repository.make_plan(set(repository.variants))
    bake = repository.render_bake(plan, "example", "1" * 40, "load", platform="linux/amd64")
    component_groups = [name for name in bake["group"] if name.startswith("component-")]
    assert len(component_groups) == 2


def test_infrastructure_changes_affect_all_but_docs_do_not(repo_root: Path) -> None:
    """Apply global rebuild rules without rebuilding for unrelated docs.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "demo", manifest("demo", [variant("one"), variant("two")]))
    repository = ImageRepository(repo_root).load()
    assert repository.affected(["tools/check_policy.py"]) == set(repository.variants)
    assert repository.affected([".dockerignore"]) == set(repository.variants)
    assert repository.affected(["uv.lock"]) == set(repository.variants)
    assert repository.affected([".gitmodules"]) == set(repository.variants)
    assert repository.affected(["vendor/image-kit"]) == set(repository.variants)
    assert repository.affected(["docs/development.md"]) == set()


def test_missing_submodule_input_reports_initialization_command(repo_root: Path) -> None:
    """Explain how to initialize missing shared inputs after a plain clone.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    data = manifest("demo", [variant("one")])
    data["inputs"] = ["vendor/example/scripts/dev/cmake.sh"]
    write_family(repo_root, "demo", data)
    with pytest.raises(RepositoryError, match="git submodule update --init --recursive"):
        ImageRepository(repo_root).load()


def test_gitlink_change_rebuilds_all_variants(repo_root: Path) -> None:
    """Rebuild all images when Git reports only a changed component commit.

    Parameters
    ----------
    repo_root:
        Temporary consumer repository root.
    """
    write_family(repo_root, "one", manifest("one", [variant("base")]))
    write_family(repo_root, "two", manifest("two", [variant("base")]))
    commands = [
        ["init"],
        ["add", "."],
        ["commit", "-m", "Initial fixture"],
        ["update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},vendor/image-kit"],
        ["commit", "-m", "Add component pin"],
        ["update-index", "--cacheinfo", f"160000,{'2' * 40},vendor/image-kit"],
        ["commit", "-m", "Update component pin"],
    ]
    for command in commands:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=disabled-hooks",
                *command,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    repository = ImageRepository(repo_root).load()
    changed = repository.changed_files("HEAD~1", "HEAD")
    assert changed == ["vendor/image-kit"]
    assert repository.affected(changed) == set(repository.variants)
