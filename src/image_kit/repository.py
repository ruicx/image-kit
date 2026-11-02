"""Repository domain model and Buildx Bake graph generation."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tomllib
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema
import yaml

TargetKey = tuple[str, str]
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
PLATFORMS = ("linux/amd64", "linux/arm64")
SENSITIVE_ARGUMENT_PATTERN = re.compile(r"(?:SECRET|PASSWORD|TOKEN|PRIVATE_KEY)", re.IGNORECASE)


class RepositoryError(RuntimeError):
    """Represent a user-actionable repository configuration error."""


@dataclass(frozen=True)
class Dependency:
    """Describe an internal image dependency exposed as a BuildKit context.

    Attributes
    ----------
    context:
        Dockerfile context name used by the dependent image.
    family:
        Name of the image family that provides the dependency.
    variant:
        Variant identifier in the provider family.
    """

    context: str
    family: str
    variant: str

    @property
    def key(self) -> TargetKey:
        """Return the repository key of the dependency target.

        Returns
        -------
        TargetKey
            Return the repository key of the dependency target.
        """
        return (self.family, self.variant)


@dataclass(frozen=True)
class SmokeTest:
    """Store a smoke execution contract.

    Attributes
    ----------
    script:
        Consumer-relative script path.
    library:
        Optional helper beside the script.
    inputs:
        Additional change-detection inputs.
    policy:
        Required or helper-managed advisory assertions.
    entrypoint:
        Bash override or the original image entrypoint.
    """

    script: str
    library: str | None
    inputs: tuple[str, ...]
    policy: str
    entrypoint: str


class ManifestLoader(yaml.SafeLoader):
    """Reject duplicate or non-text YAML mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Construct a mapping with unique text keys.

        Parameters
        ----------
        node:
            YAML mapping node.
        deep:
            Whether to construct nested objects immediately.

        Returns
        -------
        dict[str, Any]
            Validated mapping.

        Raises
        ------
        RepositoryError
            If mapping keys are duplicated or are not text.
        """
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise RepositoryError(f"YAML mapping keys must be unique text: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


@dataclass(frozen=True)
class Variant:
    """Store the normalized build contract for one image variant.

    Attributes
    ----------
    family:
        Owning image family.
    identifier:
        Stable variant identifier and floating tag name.
    base_image:
        External base image including an explicit version tag.
    base_digest:
        Optional pinned digest for the external base image. ``None`` follows the
        explicit tag in ``base_image``.
    build_args:
        Non-secret Docker build arguments declared by the manifest.
    mirror:
        Optional package mirror policy selected by the manifest.
    ssh_mode:
        Optional default runtime SSH policy.
    dependencies:
        Internal image targets provided as named BuildKit contexts.
    tests:
        Smoke execution contracts.
    """

    family: str
    identifier: str
    base_image: str
    base_digest: str | None
    build_args: Mapping[str, str]
    mirror: str | None
    ssh_mode: str | None
    dependencies: tuple[Dependency, ...]
    tests: tuple[SmokeTest, ...]

    @property
    def key(self) -> TargetKey:
        """Return the unique repository key for this variant.

        Returns
        -------
        TargetKey
            Return the unique repository key for this variant.
        """
        return (self.family, self.identifier)

    @property
    def target_name(self) -> str:
        """Return the normalized Buildx Bake target name.

        Returns
        -------
        str
            Return the normalized Buildx Bake target name.
        """
        return sanitize_target(f"{self.family}--{self.identifier}")

    @property
    def base_reference(self) -> str:
        """Return the pinned reference or the explicitly tracked tag.

        Returns
        -------
        str
            Return the pinned reference or the explicitly tracked tag.
        """
        if self.base_digest is None:
            return self.base_image
        return f"{self.base_image}@{self.base_digest}"


@dataclass(frozen=True)
class Family:
    """Store a normalized image-family manifest.

    Attributes
    ----------
    name:
        Explicit published name, independent of its directory name.
    directory:
        Absolute path to the family directory.
    description:
        Human-readable family description.
    dockerfile:
        Absolute path to the parameterized Dockerfile.
    context:
        Absolute Docker build context.
    platforms:
        Target platforms accepted by the current schema.
    inputs:
        Repository-relative glob patterns that trigger family rebuilds.
    publish:
        Whether selected variants may be published from the main branch.
    variants:
        Variants released by this family.
    """

    name: str
    directory: Path
    description: str
    dockerfile: Path
    context: Path
    platforms: tuple[str, ...]
    inputs: tuple[str, ...]
    publish: bool
    variants: tuple[Variant, ...]


def sanitize_target(value: str) -> str:
    """Convert an arbitrary identifier into a Bake-compatible target name.

    Parameters
    ----------
    value:
        Identifier to normalize.

    Returns
    -------
    str
        Identifier with unsupported characters replaced by hyphens.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def registry_name(value: str) -> str:
    """Validate a container registry host with an optional port.

    Parameters
    ----------
    value:
        Registry hostname, optionally followed by a port.

    Returns
    -------
    str
        Lowercase registry hostname and optional port.

    Raises
    ------
    RepositoryError
        If a URL, credentials, or invalid registry name is supplied.
    """
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*(?::[0-9]+)?", value):
        raise RepositoryError("registry must be a hostname with an optional port")
    return value.lower()


class ImageRepository:
    """Load, validate, plan, and render a repository of image manifests.

    Parameters
    ----------
    root:
        Consumer repository root containing ``src/<family>/image.yml``.
    """

    def __init__(self, root: Path) -> None:
        """Initialize an unloaded repository model.

        Parameters
        ----------
        root:
            Repository root to inspect.
        """
        self.root = root.resolve()
        config_path = self.root / "pyproject.toml"
        try:
            config = (
                tomllib.loads(config_path.read_text(encoding="utf-8"))
                if config_path.is_file()
                else {}
            )
        except tomllib.TOMLDecodeError as error:
            raise RepositoryError(f"invalid pyproject.toml: {error}") from error
        settings = config.get("tool", {}).get("image-kit", {})
        if not isinstance(settings, dict):
            raise RepositoryError("tool.image-kit: must be a TOML table")
        for name in ("rebuild-inputs", "shell-inputs"):
            value = settings.get(name, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise RepositoryError(f"tool.image-kit.{name}: must be a list of path patterns")
        self.rebuild_inputs = (
            ".dockerignore",
            "pyproject.toml",
            "uv.lock",
            ".github/workflows/**",
            *settings.get("rebuild-inputs", []),
        )
        self.shell_inputs = tuple(settings.get("shell-inputs", []))
        self.registry = registry_name(str(settings.get("registry", "ghcr.io")))
        self.source_repository = settings.get("source-repository")
        if self.source_repository is not None and not isinstance(self.source_repository, str):
            raise RepositoryError("tool.image-kit.source-repository: expected a string")
        if "manifest-format" in settings:
            raise RepositoryError(
                "manifest-format was removed; migrate manifests to schema_version: 2"
            )
        self.families: dict[str, Family] = {}
        self.variants: dict[TargetKey, Variant] = {}

    def path(self, value: str) -> Path:
        """Resolve a repository-relative file or pattern without allowing escapes.

        Parameters
        ----------
        value:
            Portable relative path.

        Returns
        -------
        Path
            Absolute path inside the consumer root.

        Raises
        ------
        RepositoryError
            If the path or its symlink target escapes the consumer.
        """
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or "\\" in value or ":" in value:
            raise RepositoryError(f"path must stay inside the repository: {value}")
        result = self.root / value
        if not result.resolve().is_relative_to(self.root):
            raise RepositoryError(f"path escapes repository: {value}")
        return result

    def load(self) -> ImageRepository:
        """Load v2 manifests using the package schema and validate the complete graph.

        Returns
        -------
        ImageRepository
            Populated repository.

        Raises
        ------
        RepositoryError
            If schema, input paths, identifiers or dependencies are invalid.
        """
        schema = json.loads(
            files("image_kit").joinpath("schemas/image.schema.json").read_text(encoding="utf-8")
        )
        validator = jsonschema.Draft202012Validator(schema)
        self.families.clear()
        self.variants.clear()
        target_names: set[str] = set()
        for path in sorted((self.root / "src").glob("*/image.yml")):
            self.path(path.relative_to(self.root).as_posix())
            raw = yaml.load(path.read_text(encoding="utf-8"), Loader=ManifestLoader)
            if isinstance(raw, dict) and raw.get("schema_version") == 1:
                raise RepositoryError(
                    f"{path}: migrate schema_version: 1 to 2; see docs/migration-v2.md"
                )
            try:
                validator.validate(raw)
            except jsonschema.ValidationError as error:
                details = "; ".join(item.message for item in error.context)
                raise RepositoryError(
                    f"{path}: {'.'.join(map(str, error.absolute_path))}: {error.message}; {details}"
                ) from error
            family = self._parse_family(path, raw)
            if family.name in self.families:
                raise RepositoryError(f"duplicate image name: {family.name}")
            self.families[family.name] = family
            for variant in family.variants:
                if variant.key in self.variants:
                    raise RepositoryError(
                        f"duplicate variant: {variant.family}/{variant.identifier}"
                    )
                if variant.target_name in target_names:
                    raise RepositoryError(f"colliding Bake target name: {variant.target_name}")
                self.variants[variant.key] = variant
                target_names.add(variant.target_name)
        if not self.families:
            raise RepositoryError("no manifests found under src/*/image.yml")
        self._validate_paths_and_dependencies()
        self.topological_order()
        return self

    def _parse_family(self, path: Path, raw: dict[str, Any]) -> Family:
        """Normalize a v2 manifest into immutable models.

        Parameters
        ----------
        path:
            Manifest location, independent of its published name.
        raw:
            Schema-valid manifest.

        Returns
        -------
        Family
            Normalized image family.
        """
        variants: list[Variant] = []
        for item in raw["variants"]:
            base = item["base"]
            dependencies = ()
            if "target" in base:
                parent, version = base["target"].split("/")
                dependencies = (Dependency(base["context"], parent, version),)
            variants.append(
                Variant(
                    family=raw["name"],
                    identifier=item["id"],
                    base_image=base.get("image", base.get("context", "")),
                    base_digest=base.get("digest"),
                    build_args={
                        key: str(value).lower() if isinstance(value, bool) else str(value)
                        for key, value in item["build_args"].items()
                    },
                    mirror=item.get("mirror"),
                    ssh_mode=item.get("runtime", {}).get("ssh", {}).get("mode"),
                    dependencies=dependencies,
                    tests=tuple(
                        SmokeTest(
                            test["script"],
                            test.get("library"),
                            tuple(test.get("inputs", [])),
                            test.get("policy", "required"),
                            test.get("entrypoint", "bash"),
                        )
                        for test in item["tests"]
                    ),
                )
            )
        return Family(
            name=raw["name"],
            directory=path.parent,
            description=raw["description"],
            dockerfile=self.path(raw["dockerfile"]),
            context=self.path(raw["context"]),
            platforms=tuple(raw["platforms"]),
            inputs=tuple(raw["inputs"]),
            publish=raw["publish"],
            variants=tuple(variants),
        )

    def _input_files(self, pattern: str) -> list[Path]:
        """Resolve a declared input to files within the repository.

        Parameters
        ----------
        pattern:
            Relative glob or file path.

        Returns
        -------
        list[Path]
            Validated matches.

        Raises
        ------
        RepositoryError
            If an input is missing, is a directory or escapes the root.
        """
        self.path(pattern)
        matches = list(self.root.glob(pattern))
        if not matches or any(not path.is_file() for path in matches):
            raise RepositoryError(
                f"input must match files: {pattern}; for submodule inputs, run "
                "git submodule update --init --recursive"
            )
        for path in matches:
            self.path(path.relative_to(self.root).as_posix())
        return matches

    def _validate_paths_and_dependencies(self) -> None:
        """Validate paths, external bases, smoke contracts and parent coverage.

        Raises
        ------
        RepositoryError
            If any semantic build contract is invalid.
        """
        for family in self.families.values():
            if not family.dockerfile.is_file():
                raise RepositoryError(f"{family.name}: missing Dockerfile")
            for pattern in family.inputs:
                self._input_files(pattern)
            for variant in family.variants:
                if not variant.dependencies and (
                    not re.search(r":[^/:@]+$", variant.base_image)
                    or variant.base_image.endswith((":latest", ":master"))
                ):
                    raise RepositoryError(
                        f"{family.name}: external base requires an explicit version tag"
                    )
                if sensitive := sorted(
                    key for key in variant.build_args if SENSITIVE_ARGUMENT_PATTERN.search(key)
                ):
                    raise RepositoryError(f"{family.name}: secret-like keys forbidden: {sensitive}")
                for dependency in variant.dependencies:
                    if dependency.key not in self.variants:
                        raise RepositoryError(
                            f"unknown target {dependency.family}/{dependency.variant}"
                        )
                    if not set(family.platforms).issubset(
                        self.families[dependency.family].platforms
                    ):
                        raise RepositoryError(
                            f"{family.name}: dependency must support its platforms"
                        )
                for test in variant.tests:
                    script = self.path(test.script)
                    if not script.is_file():
                        raise RepositoryError(f"{family.name}: missing smoke script {test.script}")
                    if test.library:
                        library = self.path(test.library)
                        if not library.is_file() or library.parent != script.parent:
                            raise RepositoryError("smoke library must exist beside its script")
                        if test.library not in test.inputs:
                            raise RepositoryError("smoke inputs must include the library")
                    for pattern in test.inputs:
                        self._input_files(pattern)

    def shell_files(self) -> list[Path]:
        """List manifest and configured shell inputs.

        Returns
        -------
        list[Path]
            Sorted shell scripts.
        """
        paths: set[Path] = set()
        for pattern in self.shell_inputs:
            paths.update(self._input_files(pattern))
        for family in self.families.values():
            for pattern in family.inputs:
                paths.update(self._input_files(pattern))
            for variant in family.variants:
                for test in variant.tests:
                    paths.add(self.path(test.script))
                    for pattern in test.inputs:
                        paths.update(self._input_files(pattern))
        return sorted(path for path in paths if path.suffix == ".sh")

    def topological_order(self, subset: Iterable[TargetKey] | None = None) -> list[TargetKey]:
        """Order image variants so every dependency precedes its consumers.

        Parameters
        ----------
        subset:
            Optional target subset. Dependencies outside the subset are ignored.

        Returns
        -------
        list[TargetKey]
            Deterministic topological ordering.

        Raises
        ------
        RepositoryError
            If the selected graph contains a dependency cycle.
        """
        selected = set(subset if subset is not None else self.variants)
        indegree = {key: 0 for key in selected}
        children: dict[TargetKey, list[TargetKey]] = defaultdict(list)
        for key in selected:
            for dependency in self.variants[key].dependencies:
                if dependency.key in selected:
                    indegree[key] += 1
                    children[dependency.key].append(key)
        ready = deque(sorted(key for key, degree in indegree.items() if degree == 0))
        result: list[TargetKey] = []
        while ready:
            key = ready.popleft()
            result.append(key)
            for child in sorted(children[key]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(result) != len(selected):
            cyclic = sorted(key for key, degree in indegree.items() if degree > 0)
            formatted = ", ".join(f"{family}/{variant}" for family, variant in cyclic)
            raise RepositoryError(f"image dependency graph contains a cycle: {formatted}")
        return result

    def component_groups(self, subset: Iterable[TargetKey]) -> list[set[TargetKey]]:
        """Partition targets into independent undirected graph components.

        Parameters
        ----------
        subset:
            Targets to partition.

        Returns
        -------
        list[set[TargetKey]]
            Components that can be built and tested independently.
        """
        selected = set(subset)
        adjacency: dict[TargetKey, set[TargetKey]] = {key: set() for key in selected}
        for key in selected:
            for dependency in self.variants[key].dependencies:
                if dependency.key in selected:
                    adjacency[key].add(dependency.key)
                    adjacency[dependency.key].add(key)

        groups: list[set[TargetKey]] = []
        remaining = set(selected)
        while remaining:
            seed = min(remaining)
            group = {seed}
            queue = deque([seed])
            remaining.remove(seed)
            while queue:
                for neighbour in sorted(adjacency[queue.popleft()]):
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        group.add(neighbour)
                        queue.append(neighbour)
            groups.append(group)
        return groups

    def changed_files(self, base: str, head: str) -> list[str]:
        """Read both sides of renames and deletions between explicit revisions.

        Parameters
        ----------
        base:
            Diff base; callers resolve PR merge bases explicitly.
        head:
            Diff head.

        Returns
        -------
        list[str]
            Changed consumer-relative paths.
        """
        return subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", base, head, "--"],
            cwd=self.root,
            text=True,
        ).splitlines()

    def affected(self, changed_files: Sequence[str]) -> set[TargetKey]:
        """Calculate directly changed variants and all transitive consumers.

        Parameters
        ----------
        changed_files:
            Repository-relative changed paths.

        Returns
        -------
        set[TargetKey]
            Publish targets affected by the changes.
        """
        direct: set[TargetKey]
        if any(
            fnmatch.fnmatchcase(path, pattern)
            for path in changed_files
            for pattern in self.rebuild_inputs
        ):
            direct = set(self.variants)
        else:
            direct = set()
            for family in self.families.values():
                patterns = [
                    family.dockerfile.relative_to(self.root).as_posix(),
                    (family.directory / "image.yml").relative_to(self.root).as_posix(),
                    *family.inputs,
                ]
                if any(
                    fnmatch.fnmatchcase(path, pattern)
                    for path in changed_files
                    for pattern in patterns
                ):
                    direct.update(variant.key for variant in family.variants)

                for variant in family.variants:
                    test_patterns = [
                        pattern for test in variant.tests for pattern in (test.script, *test.inputs)
                    ]
                    if any(
                        fnmatch.fnmatchcase(path, pattern)
                        for path in changed_files
                        for pattern in test_patterns
                    ):
                        direct.add(variant.key)

        # Reverse edges let a changed base propagate to every transitive consumer.
        reverse: dict[TargetKey, set[TargetKey]] = defaultdict(set)
        for key, variant in self.variants.items():
            for dependency in variant.dependencies:
                reverse[dependency.key].add(key)
        affected = set(direct)
        queue = deque(direct)
        while queue:
            for child in reverse[queue.popleft()]:
                if child not in affected:
                    affected.add(child)
                    queue.append(child)
        return affected

    def build_closure(self, publish_targets: Iterable[TargetKey]) -> set[TargetKey]:
        """Add every transitive build dependency required by publish targets.

        Parameters
        ----------
        publish_targets:
            Variants selected for testing or publication.

        Returns
        -------
        set[TargetKey]
            Selected targets plus their transitive ancestors.
        """
        # Publication selection expands upward so internal bases are built from this commit.
        closure = set(publish_targets)
        queue = deque(closure)
        while queue:
            for dependency in self.variants[queue.popleft()].dependencies:
                if dependency.key not in closure:
                    closure.add(dependency.key)
                    queue.append(dependency.key)
        return closure

    def select(self, family: str | None = None, target: str | None = None) -> set[TargetKey]:
        """Resolve an explicit family, exact target or all targets.

        Parameters
        ----------
        family:
            YAML image name.
        target:
            Exact name/variant reference.

        Returns
        -------
        set[TargetKey]
            Requested build outputs.

        Raises
        ------
        RepositoryError
            If selection names are unknown or ambiguous.
        """
        if family and target:
            raise RepositoryError("choose either --family or --target")
        if target:
            parts = target.split("/")
            if len(parts) != 2 or (parts[0], parts[1]) not in self.variants:
                raise RepositoryError(f"unknown target {target}")
            return {(parts[0], parts[1])}
        if family:
            if family not in self.families:
                raise RepositoryError(f"unknown family {family}")
            return {variant.key for variant in self.families[family].variants}
        return set(self.variants)

    def make_plan(
        self,
        publish_targets: Iterable[TargetKey],
        changed_files: Sequence[str] = (),
        platform: str | None = None,
    ) -> dict[str, Any]:
        """Plan native workers and ancestors without expanding publication selection.

        Parameters
        ----------
        publish_targets:
            Explicitly selected output keys.
        changed_files:
            Diagnostic changed paths.
        platform:
            Optional platform filter before adding ancestors.

        Returns
        -------
        dict[str, Any]
            Deterministic v2 plan.

        Raises
        ------
        RepositoryError
            If the selection or platform is unsupported.
        """
        selected = set(publish_targets)
        if selected - self.variants.keys():
            raise RepositoryError("plan contains unknown targets")
        if platform is not None and platform not in PLATFORMS:
            raise RepositoryError(f"unsupported platform {platform}")
        if platform:
            selected = {key for key in selected if platform in self.families[key[0]].platforms}
        closure = self.build_closure(selected)
        platforms = {
            key: ({platform} if platform else set(self.families[key[0]].platforms))
            for key in selected
        }
        ordered = self.topological_order(closure)
        for key in reversed(ordered):
            for dependency in self.variants[key].dependencies:
                platforms.setdefault(dependency.key, set()).update(platforms[key])
        targets: list[dict[str, Any]] = [
            {
                "name": key[0],
                "variant": key[1],
                "target": self.variants[key].target_name,
                "platforms": [item for item in PLATFORMS if item in platforms[key]],
                "publish": key in selected and self.families[key[0]].publish,
                "reason": "selected" if key in selected else "dependency",
            }
            for key in ordered
        ]
        matrix = [
            {
                "platform": item,
                "platform_id": item.split("/")[1],
                "runner": "ubuntu-24.04" if item == "linux/amd64" else "ubuntu-24.04-arm",
            }
            for item in PLATFORMS
            if any(item in target["platforms"] for target in targets)
        ]
        return {
            "schema_version": 2,
            "changed_files": list(changed_files),
            "platform": platform,
            "targets": targets,
            "build_matrix": {"include": matrix},
        }

    def check_plan(self, plan: Mapping[str, Any]) -> None:
        """Reject stale, malformed or edited build plans.

        Parameters
        ----------
        plan:
            Candidate generated plan.

        Raises
        ------
        RepositoryError
            If the plan does not exactly match current manifests and selection.
        """
        try:
            selected = {
                (item["name"], item["variant"])
                for item in plan["targets"]
                if item["reason"] == "selected"
            }
            expected = self.make_plan(selected, plan["changed_files"], plan["platform"])
        except (KeyError, TypeError) as error:
            raise RepositoryError("malformed v2 build plan") from error
        if plan != expected:
            raise RepositoryError("build plan does not match current manifests")

    def render_bake(
        self,
        plan: Mapping[str, Any],
        owner: str,
        revision: str,
        mode: str,
        source_repository: str | None = None,
        build_id: str | None = None,
        registry: str | None = None,
        *,
        platform: str,
        github_cache: bool = False,
    ) -> dict[str, Any]:
        """Render one native platform of the common dependency graph.

        Parameters
        ----------
        plan:
            Complete v2 plan.
        owner:
            Registry namespace.
        revision:
            Full source SHA.
        mode:
            Load or digest publication.
        source_repository:
            OCI source URL or owner/repository; defaults to consumer configuration.
        build_id:
            Run-id-attempt; required for publication.
        registry:
            Optional registry override.
        platform:
            Native worker platform.
        github_cache:
            Explicit Actions cache opt-in.

        Returns
        -------
        dict[str, Any]
            Bake targets and independent component groups.

        Raises
        ------
        RepositoryError
            If identity, plan, platform or mode is invalid.
        """
        self.check_plan(plan)
        if mode not in ("load", "publish") or platform not in PLATFORMS:
            raise RepositoryError("Bake requires load/publish and a native platform")
        if mode == "publish" and build_id is None:
            raise RepositoryError("publication requires --build-id")
        suffix = release_suffix(revision, build_id)
        host = registry_name(registry or self.registry)
        namespace = owner_name(owner)
        targets: dict[str, Any] = {}
        keys: set[TargetKey] = set()
        for item in plan["targets"]:
            if platform not in item["platforms"]:
                continue
            key = (item["name"], item["variant"])
            keys.add(key)
            variant = self.variants[key]
            family = self.families[key[0]]
            version = f"{variant.identifier}-{suffix}"
            if len(version) > 128:
                raise RepositoryError(f"generated tag exceeds 128 characters: {version}")
            image_path = f"{host}/{namespace}/{family.name}"
            args = {
                **variant.build_args,
                "BASE_IMAGE": variant.base_reference,
                "IMAGE_REVISION": revision.lower(),
                "IMAGE_VERSION": version,
            }
            if variant.mirror is not None:
                args["PACKAGE_MIRROR"] = variant.mirror
            if variant.ssh_mode is not None:
                args["SSH_MODE"] = variant.ssh_mode
            target: dict[str, Any] = {
                "context": ".",
                "dockerfile": family.dockerfile.relative_to(self.root).as_posix(),
                "platforms": [platform],
                "pull": True,
                "args": args,
                "contexts": {
                    dependency.context: f"target:{self.variants[dependency.key].target_name}"
                    for dependency in variant.dependencies
                },
                "labels": {
                    "org.opencontainers.image.revision": revision.lower(),
                    "org.opencontainers.image.version": version,
                    "org.opencontainers.image.title": family.name,
                },
            }
            source = source_repository or self.source_repository
            if source:
                target["labels"]["org.opencontainers.image.source"] = (
                    source
                    if source.startswith(("https://", "http://"))
                    else f"https://github.com/{source}"
                )
            scope = f"{variant.target_name}-{platform.split('/')[1]}"
            if github_cache:
                target["cache-from"] = [f"type=gha,scope={scope}"]
            if mode == "load":
                target.update(tags=[f"{image_path}:{version}"], output=["type=docker"])
            else:
                target["output"] = (
                    [
                        f"type=image,name={image_path},push-by-digest=true,name-canonical=true,push=true"
                    ]
                    if item["publish"]
                    else ["type=cacheonly"]
                )
                if github_cache:
                    target["cache-to"] = [f"type=gha,mode=max,scope={scope}"]
            targets[variant.target_name] = target
        groups = {"default": {"targets": list(targets)}}
        for index, group in enumerate(self.component_groups(keys)):
            groups[f"component-{index}"] = {
                "targets": [self.variants[key].target_name for key in self.topological_order(group)]
            }
        return {"group": groups, "target": targets}


def owner_name(value: str) -> str:
    """Validate a registry namespace.

    Parameters
    ----------
    value:
        Owner or organization name.

    Returns
    -------
    str
        Lowercase namespace.

    Raises
    ------
    RepositoryError
        If the namespace contains invalid characters.
    """
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", value):
        raise RepositoryError("invalid registry owner")
    return value.lower()


def release_suffix(revision: str, build_id: str | None = None) -> str:
    """Create a source and build identity shared by all pipeline stages.

    Parameters
    ----------
    revision:
        Full forty-character Git SHA.
    build_id:
        Positive run-id-attempt, or None for local load/test only.

    Returns
    -------
    str
        Twelve-character SHA followed by the build ID or local marker.

    Raises
    ------
    RepositoryError
        If revision or build ID is invalid.
    """
    if not SHA_PATTERN.fullmatch(revision):
        raise RepositoryError("revision must be a full forty-character Git SHA")
    if build_id is not None and not re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*", build_id):
        raise RepositoryError("build-id must use positive numeric run-id-attempt format")
    return f"{revision[:12].lower()}-{build_id or 'local'}"


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk.

    Parameters
    ----------
    path:
        JSON file to read.

    Returns
    -------
    dict[str, Any]
        Parsed JSON object.

    Raises
    ------
    RepositoryError
        If the JSON root is not an object.
    """
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RepositoryError(f"JSON root must be an object: {path}")
    return loaded


def write_json(data: Mapping[str, Any], output: Path | None) -> None:
    """Write deterministic JSON to a file or standard output.

    Parameters
    ----------
    data:
        Mapping to serialize.
    output:
        Destination path, or ``None`` to print to standard output.
    """
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
