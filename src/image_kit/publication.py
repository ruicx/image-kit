"""Validate native digest artifacts and promote verified registry manifests."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .repository import (
    PLATFORMS,
    RepositoryError,
    owner_name,
    registry_name,
    release_suffix,
)

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
VERSION = re.compile(
    r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
)


@dataclass(frozen=True)
class BuildIdentity:
    """Identify a publication across native workers and promotion stages.

    Attributes
    ----------
    registry:
        Registry hostname and optional port.
    owner:
        Registry namespace.
    repository:
        Source repository URL or owner/repository identifier.
    revision:
        Full source revision.
    build_id:
        Positive numeric run-id-attempt.
    """

    registry: str
    owner: str
    repository: str
    revision: str
    build_id: str

    def validate(self) -> None:
        """Require a complete, normalized publication identity.

        Raises
        ------
        RepositoryError
            If identity fields are malformed or local-only.
        """
        release_suffix(self.revision, self.build_id)
        if not self.build_id or not self.repository:
            raise RepositoryError("publication requires source repository and build-id")
        if self.registry != registry_name(self.registry) or self.owner != owner_name(
            self.owner
        ):
            raise RepositoryError(
                "publication identity must use normalized registry and owner"
            )
        if self.revision != self.revision.lower():
            raise RepositoryError("publication revision must be lowercase")

    def image(self, name: str, tag: str) -> str:
        """Build a validated image reference.

        Parameters
        ----------
        name:
            YAML published image name.
        tag:
            Generated version or floating tag.

        Returns
        -------
        str
            Registry reference.

        Raises
        ------
        RepositoryError
            If image name or tag cannot be published.
        """
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise RepositoryError(f"invalid image name: {name}")
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}", tag):
            raise RepositoryError(f"invalid or oversized tag: {tag}")
        return f"{self.registry}/{self.owner}/{name}:{tag}"


def collect(
    plan: Mapping[str, Any],
    metadata: Mapping[str, Any],
    identity: BuildIdentity,
    platform: str,
) -> dict[str, Any]:
    """Collect publishable native digests from file-loaded Bake metadata.

    Parameters
    ----------
    plan:
        Validated complete plan.
    metadata:
        Bake metadata read through files, never environment variables.
    identity:
        Native build identity.
    platform:
        Worker platform.

    Returns
    -------
    dict[str, Any]
        Versioned native artifact.

    Raises
    ------
    RepositoryError
        If the platform or an exporter digest is invalid.
    """
    identity.validate()
    if platform not in PLATFORMS:
        raise RepositoryError(f"unsupported platform: {platform}")
    records = []
    for item in plan["targets"]:
        if not item["publish"] or platform not in item["platforms"]:
            continue
        digest = metadata.get(item["target"], {}).get("containerimage.digest", "")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise RepositoryError(
                f"missing or invalid digest metadata: {item['target']}"
            )
        records.append(
            {
                "name": item["name"],
                "variant": item["variant"],
                "platform": platform,
                "digest": digest,
            }
        )
    return {
        "schema_version": 2,
        "kind": "native-digests",
        "identity": asdict(identity),
        "digests": records,
    }


def _inspect(reference: str, *, missing_ok: bool = False) -> dict[str, Any] | None:
    """Read a registry descriptor and distinguish missing tags from lookup failures.

    Parameters
    ----------
    reference:
        Registry tag or digest reference.
    missing_ok:
        Accept an explicit manifest-not-found response.

    Returns
    -------
    dict[str, Any] or None
        Manifest descriptor, or None for an explicitly absent optional tag.

    Raises
    ------
    RepositoryError
        If inspection, authentication, transport or descriptor validation fails.
    """
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{json .Manifest}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        error = result.stderr.strip()
        absent = re.search(
            r"\b(?:manifest_unknown|name_unknown|manifest unknown)\b",
            error,
            re.IGNORECASE,
        )
        absent = absent or re.search(
            rf"(?:^|\n)(?:ERROR: )?{re.escape(reference)}: not found$", error
        )
        denied = re.search(
            r"unauthorized|denied|forbidden|timeout|credential", error, re.IGNORECASE
        )
        if missing_ok and absent and not denied:
            return None
        raise RepositoryError(f"registry inspection failed for {reference}: {error}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or not DIGEST.fullmatch(
        str(value.get("digest", ""))
    ):
        raise RepositoryError(f"invalid registry descriptor: {reference}")
    return value


def _document(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Remove inspection-only fields before comparing actual index documents.

    Parameters
    ----------
    descriptor:
        Manifest descriptor from registry inspection.

    Returns
    -------
    dict[str, Any]
        Index document without synthetic digest and size fields.
    """
    return {
        key: value for key, value in descriptor.items() if key not in ("digest", "size")
    }


def _platforms(document: Mapping[str, Any]) -> set[str]:
    """Read native platforms while retaining provenance descriptors in the document.

    Parameters
    ----------
    document:
        OCI index or Docker manifest list.

    Returns
    -------
    set[str]
        Runnable platforms, excluding recognized attestation manifests.

    Raises
    ------
    RepositoryError
        If descriptors are malformed, duplicated, or contain unidentified platforms.
    """
    platforms: list[str] = []
    for item in document.get("manifests", []):
        if not DIGEST.fullmatch(str(item.get("digest", ""))):
            raise RepositoryError("index contains an invalid manifest digest")
        platform = item.get("platform", {})
        value = f"{platform.get('os')}/{platform.get('architecture')}"
        if (
            item.get("annotations", {}).get("vnd.docker.reference.type")
            == "attestation-manifest"
        ):
            continue
        if value not in PLATFORMS:
            raise RepositoryError(f"index contains an unsupported platform: {value}")
        platforms.append(value)
    if not platforms or len(platforms) != len(set(platforms)):
        raise RepositoryError("index contains missing or duplicate native platforms")
    return set(platforms)


def _create(reference: str, sources: Sequence[str], *, dry_run: bool = False) -> None:
    """Create a registry tag or print the intended mutation.

    Parameters
    ----------
    reference:
        Destination tag.
    sources:
        Immutable source digest references.
    dry_run:
        Print without mutation.
    """
    command = ["docker", "buildx", "imagetools", "create", "--tag", reference, *sources]
    print(json.dumps(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True)


def merge(
    plan: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    identity: BuildIdentity,
    ref: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Validate all native artifacts before publishing build and floating tags.

    Parameters
    ----------
    plan:
        Validated complete build plan.
    artifacts:
        Native worker JSON artifacts.
    identity:
        Expected build identity.
    ref:
        Source Git ref; only main advances floating tags.
    dry_run:
        Inspect and print mutations without publishing a receipt.

    Returns
    -------
    dict[str, Any] or None
        Publication receipt after successful mutations; None for dry runs.

    Raises
    ------
    RepositoryError
        If artifacts, expected platforms or existing immutable tags conflict.
    subprocess.CalledProcessError
        If a registry mutation fails.
    """
    identity.validate()
    expected = {
        (item["name"], item["variant"], platform)
        for item in plan["targets"]
        if item["publish"]
        for platform in item["platforms"]
    }
    found: dict[tuple[str, str, str], str] = {}
    for artifact in artifacts:
        if (
            artifact.get("schema_version") != 2
            or artifact.get("kind") != "native-digests"
            or artifact.get("identity") != asdict(identity)
        ):
            raise RepositoryError(
                "native artifact belongs to a different build or schema"
            )
        for record in artifact["digests"]:
            key = (record["name"], record["variant"], record["platform"])
            if (
                key not in expected
                or key in found
                or not DIGEST.fullmatch(str(record["digest"]))
            ):
                raise RepositoryError(
                    f"duplicate, unexpected or invalid native digest: {key}"
                )
            found[key] = record["digest"]
    if found.keys() != expected:
        raise RepositoryError(
            f"missing native digests: {sorted(expected - found.keys())}"
        )
    prepared: list[
        tuple[dict[str, Any], str, list[str], dict[str, Any], dict[str, Any] | None]
    ] = []
    suffix = release_suffix(identity.revision, identity.build_id)
    for item in plan["targets"]:
        if not item["publish"]:
            continue
        reference = identity.image(item["name"], f"{item['variant']}-{suffix}")
        image_path = reference.rsplit(":", 1)[0]
        sources = [
            f"{image_path}@{found[item['name'], item['variant'], platform]}"
            for platform in item["platforms"]
        ]
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "create", "--dry-run", *sources],
            capture_output=True,
            text=True,
            check=True,
        )
        document = json.loads(result.stdout)
        if not isinstance(document, dict) or _platforms(document) != set(
            item["platforms"]
        ):
            raise RepositoryError(
                f"registry sources do not cover planned platforms: {reference}"
            )
        existing = _inspect(reference, missing_ok=True)
        if existing is not None and _document(existing) != document:
            raise RepositoryError(f"immutable tag conflict: {reference}")
        prepared.append((item, reference, sources, document, existing))
    records = []
    # Preflight the entire batch before the first public tag mutation.
    for item, reference, sources, document, existing in prepared:
        if existing is None:
            _create(reference, sources, dry_run=dry_run)
        if dry_run:
            continue
        actual = existing if existing is not None else _inspect(reference)
        if actual is None or _document(actual) != document:
            raise RepositoryError(
                f"published index does not match verified sources: {reference}"
            )
        records.append(
            {
                "name": item["name"],
                "variant": item["variant"],
                "tag": reference.rsplit(":", 1)[1],
                "platforms": item["platforms"],
                "digest": actual["digest"],
            }
        )
    # All immutable build tags must succeed before any environment alias advances.
    if ref == "refs/heads/main":
        for record in records:
            floating = identity.image(record["name"], record["variant"])
            _create(floating, [f"{floating.rsplit(':', 1)[0]}@{record['digest']}"])
        if dry_run:
            for item, reference, _, _, _ in prepared:
                _create(
                    identity.image(item["name"], item["variant"]),
                    [reference],
                    dry_run=True,
                )
    if dry_run:
        return None
    return {
        "schema_version": 2,
        "kind": "publication",
        "identity": asdict(identity),
        "ref": ref,
        "targets": records,
    }


def release(
    publication: Mapping[str, Any],
    identity: BuildIdentity,
    version: str,
    *,
    dry_run: bool = False,
) -> None:
    """Promote a verified main publication receipt without rebuilding images.

    Parameters
    ----------
    publication:
        Receipt downloaded from the selected successful publication run.
    identity:
        Expected registry, owner, source revision and run identity.
    version:
        v-prefixed semantic release version without build metadata.
    dry_run:
        Inspect all sources and print intended mutations only.

    Raises
    ------
    RepositoryError
        If receipt identity, sources, platforms or immutable version tags conflict.
    subprocess.CalledProcessError
        If a registry operation fails.
    """
    identity.validate()
    if not VERSION.fullmatch(version):
        raise RepositoryError(
            "version must use vMAJOR.MINOR.PATCH with an optional prerelease"
        )
    if (
        publication.get("schema_version") != 2
        or publication.get("kind") != "publication"
        or publication.get("identity") != asdict(identity)
        or publication.get("ref") != "refs/heads/main"
    ):
        raise RepositoryError(
            "release requires a matching verified main publication receipt"
        )
    prepared: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    suffix = release_suffix(identity.revision, identity.build_id)
    for item in publication["targets"]:
        source = identity.image(item["name"], f"{item['variant']}-{suffix}")
        destination = identity.image(item["name"], f"{item['variant']}-{version}")
        if (
            destination in seen
            or item["tag"] != source.rsplit(":", 1)[1]
            or not DIGEST.fullmatch(str(item["digest"]))
        ):
            raise RepositoryError(
                "publication receipt contains duplicate or invalid targets"
            )
        seen.add(destination)
        current = _inspect(source)
        if (
            current is None
            or current["digest"] != item["digest"]
            or _platforms(current) != set(item["platforms"])
        ):
            raise RepositoryError(
                f"publication source no longer matches its receipt: {source}"
            )
        existing = _inspect(destination, missing_ok=True)
        if existing is not None and existing["digest"] != item["digest"]:
            raise RepositoryError(f"immutable version tag conflict: {destination}")
        prepared.append(
            (
                destination,
                f"{source.rsplit(':', 1)[0]}@{item['digest']}",
                existing is not None,
            )
        )
    if not prepared:
        raise RepositoryError("publication receipt contains no release targets")
    for destination, source, exists in prepared:
        if not exists:
            _create(destination, [source], dry_run=dry_run)
            if not dry_run:
                actual = _inspect(destination)
                if actual is None or actual["digest"] != source.split("@", 1)[1]:
                    raise RepositoryError(
                        "released tag does not match its verified digest: "
                        f"{destination}"
                    )
