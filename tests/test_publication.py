"""Exercise native artifacts, provenance indexes and immutable release promotion."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

import pytest

from image_kit.publication import (
    BuildIdentity,
    _inspect,
    collect,
    image_config_digest,
    merge,
    release,
)
from image_kit.repository import RepositoryError


@dataclass
class Registry:
    """Simulate registry documents and Docker operations within one test.

    Attributes
    ----------
    documents:
        Indexes keyed by their content digests.
    tags:
        Mutable tag references.
    commands:
        Captured command vectors.
    error:
        Optional inspection error.
    fail_tag:
        Optional destination whose write fails.
    """

    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    error: str | None = None
    fail_tag: str | None = None

    def store(self, document: dict[str, Any]) -> str:
        """Store a simulated index using a deterministic content digest.

        Parameters
        ----------
        document:
            Index document.

        Returns
        -------
        str
            Content digest.
        """
        digest = (
            "sha256:"
            + hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        )
        self.documents[digest] = document
        return digest

    def run(
        self, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        """Simulate inspect, dry-run index composition and tag creation.

        Parameters
        ----------
        command:
            Docker argument vector.
        **kwargs:
            Subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Simulated process output.

        Raises
        ------
        subprocess.CalledProcessError
            When the selected mutation is configured to fail.
        """
        self.commands.append(command)
        if "inspect" in command:
            reference = command[4]
            digest = self.tags.get(reference, reference.split("@")[-1])
            if self.error or digest not in self.documents:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr=self.error or f"ERROR: {reference}: not found",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {**self.documents[digest], "digest": digest, "size": 1}
                ),
                stderr="",
            )
        dry = "--dry-run" in command
        sources = command[5:] if dry else command[6:]
        documents = [self.documents[source.split("@")[-1]] for source in sources]
        if len(documents) == 1:
            document = copy.deepcopy(documents[0])
        else:
            members = [item for source in documents for item in source["manifests"]]
            document = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": members,
            }
        if dry:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(document), stderr=""
            )
        destination = command[5]
        if destination == self.fail_tag:
            raise subprocess.CalledProcessError(1, command)
        self.tags[destination] = self.store(document)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


@pytest.fixture
def identity() -> BuildIdentity:
    """Provide one normalized publication identity.

    Returns
    -------
    BuildIdentity
        Main build identity.
    """
    return BuildIdentity(
        "registry.example:5000", "example", "example/images", "a" * 40, "123-2"
    )


@pytest.fixture
def plan() -> dict[str, Any]:
    """Provide one two-platform published target and a private ancestor.

    Returns
    -------
    dict[str, Any]
        Validated plan projection used by publication services.
    """
    return {
        "targets": [
            {
                "name": "base",
                "variant": "stack",
                "target": "base--stack",
                "platforms": ["linux/amd64", "linux/arm64"],
                "publish": False,
            },
            {
                "name": "demo",
                "variant": "stack",
                "target": "demo--stack",
                "platforms": ["linux/amd64", "linux/arm64"],
                "publish": True,
            },
        ]
    }


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Registry:
    """Replace registry subprocesses with an isolated simulator.

    Parameters
    ----------
    monkeypatch:
        Process replacement fixture.

    Returns
    -------
    Registry
        Empty simulated registry.
    """
    result = Registry()
    monkeypatch.setattr(subprocess, "run", result.run)
    return result


def artifacts(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> list[dict[str, Any]]:
    """Seed separate native indexes with attached provenance.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native publication plan.
    identity:
        Shared worker identity.

    Returns
    -------
    list[dict[str, Any]]
        Collected native artifacts.
    """
    records = []
    for index, architecture in enumerate(("amd64", "arm64"), 1):
        document = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "digest": "sha256:" + str(index) * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "size": 1,
                    "platform": {"os": "linux", "architecture": architecture},
                },
                {
                    "digest": "sha256:" + str(index + 2) * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "size": 1,
                    "platform": {"os": "unknown", "architecture": "unknown"},
                    "annotations": {
                        "vnd.docker.reference.type": "attestation-manifest"
                    },
                },
            ],
        }
        digest = registry.store(document)
        records.append(
            collect(
                plan,
                {"demo--stack": {"containerimage.digest": digest}},
                identity,
                f"linux/{architecture}",
            )
        )
    return records


def mutations(registry: Registry) -> list[list[str]]:
    """Return registry mutations while excluding read-only dry runs.

    Parameters
    ----------
    registry:
        Captured subprocess state.

    Returns
    -------
    list[list[str]]
        Create commands that actually write tags.
    """
    return [
        command
        for command in registry.commands
        if "create" in command and "--dry-run" not in command
    ]


@pytest.mark.parametrize(
    "shape",
    [
        "index",
        "docker-list",
        "direct",
        "missing",
        "duplicate",
        "wrong-config",
        "no-config",
    ],
)
def test_registry_config_resolves_native_manifest(
    monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    """Resolve immutable native configs while excluding provenance descriptors.

    Parameters
    ----------
    monkeypatch:
        Registry subprocess replacement.
    shape:
        Registry document shape or corruption.
    """
    image = "registry.example:5000/example/demo"
    outer = "sha256:" + "a" * 64
    native = "sha256:" + "b" * 64
    config = "sha256:" + "c" * 64
    descriptor = {
        "digest": native,
        "platform": {"os": "linux", "architecture": "arm64"},
    }
    descriptors = [] if shape == "missing" else [descriptor]
    if shape == "duplicate":
        descriptors.append(descriptor)
    # Even a misleading platform label must not select an attestation.
    descriptors.append(
        {
            **descriptor,
            "digest": "sha256:" + "d" * 64,
            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
        }
    )
    index = {
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json"
        if shape == "docker-list"
        else "application/vnd.oci.image.index.v1+json",
        "manifests": descriptors,
    }
    manifest = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {} if shape == "no-config" else {"digest": config},
    }
    calls: list[list[str]] = []

    def inspect(command: list[str], **kwargs: Any) -> str:
        """Return only the selected content-addressed registry documents.

        Parameters
        ----------
        command:
            Registry inspection command.
        **kwargs:
            Subprocess options.

        Returns
        -------
        str
            Simulated JSON response.
        """
        calls.append(command)
        assert command[:4] == ["docker", "buildx", "imagetools", "inspect"]
        assert command[4] in (f"{image}@{outer}", f"{image}@{native}")
        if command[-1] == "--raw":
            return json.dumps(
                index if command[4].endswith(outer) and shape != "direct" else manifest
            )
        assert command[-2:] == ["--format", "{{json .Image}}"]
        return json.dumps(
            {
                "os": "linux",
                "architecture": "amd64" if shape == "wrong-config" else "arm64",
            }
        )

    monkeypatch.setattr(subprocess, "check_output", inspect)
    if shape in ("index", "docker-list", "direct"):
        assert image_config_digest(f"{image}@{outer}", "linux/arm64") == config
        assert len(calls) == (2 if shape == "direct" else 3)
    else:
        with pytest.raises(
            RepositoryError, match="expected one|does not match|missing config"
        ):
            image_config_digest(f"{image}@{outer}", "linux/arm64")


def test_merge_preserves_provenance_and_is_idempotent(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Merge native indexes before moving aliases, retaining attestations.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Expected worker identity.
    """
    data = artifacts(registry, plan, identity)
    receipt = merge(plan, data, identity, "refs/heads/main")
    assert receipt is not None
    record = receipt["targets"][0]
    assert len(registry.documents[record["digest"]]["manifests"]) == 4
    assert mutations(registry)[0][5].endswith(":stack-aaaaaaaaaaaa-123-2")
    assert mutations(registry)[1][5].endswith(":stack")
    registry.commands.clear()
    assert merge(plan, data, identity, "refs/heads/main") == receipt
    assert len(mutations(registry)) == 1  # Only the floating alias is reapplied.


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "revision",
        "registry",
        "build_id",
        "unexpected",
        "invalid_digest",
    ],
)
def test_artifact_damage_prevents_all_mutations(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity, damage: str
) -> None:
    """Reject incomplete or mixed worker artifacts before any registry write.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Expected identity.
    damage:
        Artifact corruption.
    """
    data = artifacts(registry, plan, identity)
    if damage == "missing":
        data.pop()
    elif damage == "duplicate":
        data.append(copy.deepcopy(data[0]))
    elif damage in ("revision", "registry", "build_id"):
        data[0]["identity"][damage] = "different"
    elif damage == "unexpected":
        data[0]["digests"][0]["name"] = "other"
    else:
        data[0]["digests"][0]["digest"] = "sha256:nope"
    with pytest.raises(RepositoryError):
        merge(plan, data, identity, "refs/heads/main")
    assert not mutations(registry)


def test_platform_mismatch_is_fatal(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Reject worker digests that do not provide the required architectures.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    data = artifacts(registry, plan, identity)
    data[1]["digests"][0]["digest"] = data[0]["digests"][0]["digest"]
    with pytest.raises(RepositoryError, match="platform"):
        merge(plan, data, identity, "refs/heads/main")
    assert not mutations(registry)


@pytest.mark.parametrize(
    "error",
    [
        "unauthorized",
        "connection timeout",
        "credential helper not found",
        "denied: manifest unknown",
    ],
)
def test_lookup_errors_are_not_missing_tags(registry: Registry, error: str) -> None:
    """Fail closed on authentication, transport and credential errors.

    Parameters
    ----------
    registry:
        Test registry.
    error:
        Docker diagnostic.
    """
    registry.error = error
    with pytest.raises(RepositoryError, match="inspection failed"):
        _inspect("registry.example/demo:missing", missing_ok=True)


def test_immutable_conflict_prevents_alias_updates(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Preserve immutable history on a repeated build identity with different content.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    data = artifacts(registry, plan, identity)
    registry.tags[identity.image("demo", "stack-aaaaaaaaaaaa-123-2")] = data[0][
        "digests"
    ][0]["digest"]
    with pytest.raises(RepositoryError, match="immutable tag conflict"):
        merge(plan, data, identity, "refs/heads/main")
    assert not mutations(registry)


def test_creation_failure_prevents_aliases(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Stop publication before moving aliases if a build-tag write fails.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    data = artifacts(registry, plan, identity)
    registry.fail_tag = identity.image("demo", "stack-aaaaaaaaaaaa-123-2")
    with pytest.raises(subprocess.CalledProcessError):
        merge(plan, data, identity, "refs/heads/main")
    assert len(mutations(registry)) == 1
    assert identity.image("demo", "stack") not in registry.tags


def test_dry_run_and_non_main_do_not_advance_aliases(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Keep dry runs read-only and branch publications free of environment promotion.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    data = artifacts(registry, plan, identity)
    assert merge(plan, data, identity, "refs/heads/main", dry_run=True) is None
    assert not mutations(registry)
    receipt = merge(plan, data, identity, "refs/heads/feature")
    assert identity.image("demo", "stack") not in registry.tags
    assert receipt is not None
    with pytest.raises(RepositoryError, match="verified main"):
        release(receipt, identity, "v1.2.0")


def test_release_promotes_verified_digest_without_building(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Create formal version tags from verified receipts and skip identical retries.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    receipt = merge(
        plan, artifacts(registry, plan, identity), identity, "refs/heads/main"
    )
    assert receipt is not None
    registry.commands.clear()
    release(receipt, identity, "v1.2.0", dry_run=True)
    assert not mutations(registry)
    release(receipt, identity, "v1.2.0")
    assert (
        registry.tags[identity.image("demo", "stack-v1.2.0")]
        == receipt["targets"][0]["digest"]
    )
    registry.commands.clear()
    release(receipt, identity, "v1.2.0")
    assert not mutations(registry)


@pytest.mark.parametrize(
    "damage",
    [
        "identity",
        "tag",
        "digest",
        "platforms",
        "duplicate",
        "empty",
        "version_conflict",
    ],
)
def test_release_rejects_tampering_before_mutation(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity, damage: str
) -> None:
    """Reject altered receipts and conflicting formal versions.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    damage:
        Receipt corruption or registry conflict.
    """
    receipt = merge(
        plan, artifacts(registry, plan, identity), identity, "refs/heads/main"
    )
    assert receipt is not None
    if damage == "identity":
        receipt["identity"]["repository"] = "other/images"
    elif damage == "duplicate":
        receipt["targets"].append(copy.deepcopy(receipt["targets"][0]))
    elif damage == "empty":
        receipt["targets"] = []
    elif damage == "version_conflict":
        registry.tags[identity.image("demo", "stack-v1.2.0")] = next(
            iter(registry.documents)
        )
    elif damage == "platforms":
        receipt["targets"][0]["platforms"] = ["linux/amd64"]
    else:
        receipt["targets"][0][damage] = "different"
    registry.commands.clear()
    with pytest.raises(RepositoryError):
        release(receipt, identity, "v1.2.0")
    assert not mutations(registry)


@pytest.mark.parametrize(
    "version", ["1.2.3", "v1.2", "v01.2.3", "v1.2.3+build", "v1.2.3-01", "v1.2.3-rc..1"]
)
def test_release_rejects_invalid_semantic_versions(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity, version: str
) -> None:
    """Reject malformed versions before accessing or changing registry state.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    version:
        Invalid formal version.
    """
    receipt = merge(
        plan, artifacts(registry, plan, identity), identity, "refs/heads/main"
    )
    assert receipt is not None
    registry.commands.clear()
    with pytest.raises(RepositoryError, match="version must"):
        release(receipt, identity, version)
    assert not registry.commands


def test_later_conflict_prevents_earlier_target_mutation(
    registry: Registry, plan: dict[str, Any], identity: BuildIdentity
) -> None:
    """Preflight every target before publishing the first build or version tag.

    Parameters
    ----------
    registry:
        Test registry.
    plan:
        Native plan.
    identity:
        Shared identity.
    """
    data = artifacts(registry, plan, identity)
    plan["targets"].append(
        {**plan["targets"][-1], "name": "other", "target": "other--stack"}
    )
    for artifact in data:
        artifact["digests"].append({**artifact["digests"][0], "name": "other"})
    other_build = identity.image("other", "stack-aaaaaaaaaaaa-123-2")
    registry.tags[other_build] = data[0]["digests"][0]["digest"]
    with pytest.raises(RepositoryError, match="immutable tag conflict"):
        merge(plan, data, identity, "refs/heads/main")
    assert not mutations(registry)
    del registry.tags[other_build]
    receipt = merge(plan, data, identity, "refs/heads/main")
    assert receipt is not None
    registry.tags[identity.image("other", "stack-v1.2.0")] = data[0]["digests"][0][
        "digest"
    ]
    registry.commands.clear()
    with pytest.raises(RepositoryError, match="immutable version tag conflict"):
        release(receipt, identity, "v1.2.0")
    assert not mutations(registry)
