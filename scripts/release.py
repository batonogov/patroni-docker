#!/usr/bin/env python3
"""Validate the release contract and render deterministic release evidence."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".github" / "release-matrix.json"
OCI_TAG_MAX_LENGTH = 128
GITHUB_MATRIX_MAX_JOBS = 256
RELEASE_EPOCH_MAJOR = 5
EXPECTED_PLATFORMS = ["linux/amd64", "linux/arm64"]
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
PG_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DISTRO_RE = re.compile(r"^[a-z][a-z0-9.-]*$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_TAG_RE = re.compile(
    r"^v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<stage>alpha|beta|rc)\.(?P<number>0|[1-9][0-9]*))?$"
)
VERIFICATION_RECEIPTS = {
    "smoke": "passed",
    "trivy": "passed",
    "sbom": "attached",
    "buildkit_provenance": "attached",
    "github_provenance": "attested",
    "ghcr_signature": "signed",
    "docker_signature": "signed",
}


class ReleaseConfigError(ValueError):
    """Raised when the checked release contract is inconsistent."""


def _require_string_list(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or not value:
        raise ReleaseConfigError(f"{key} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ReleaseConfigError(f"{key} must contain only non-empty strings")
    if len(value) != len(set(value)):
        raise ReleaseConfigError(f"{key} contains duplicate values")
    return value


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "patroni_version",
        "postgres_versions",
        "distros",
        "platforms",
    }
    if set(config) != required:
        missing = sorted(required - set(config))
        unknown = sorted(set(config) - required)
        raise ReleaseConfigError(f"release config keys differ: missing={missing}, unknown={unknown}")
    if config["schema_version"] != 1 or isinstance(config["schema_version"], bool):
        raise ReleaseConfigError("schema_version must be 1")

    patroni = config["patroni_version"]
    if not isinstance(patroni, str) or not VERSION_RE.fullmatch(patroni):
        raise ReleaseConfigError("patroni_version must be X.Y.Z")

    postgres_versions = _require_string_list(config, "postgres_versions")
    distros = _require_string_list(config, "distros")
    platforms = _require_string_list(config, "platforms")

    for version in postgres_versions:
        if not PG_VERSION_RE.fullmatch(version):
            raise ReleaseConfigError(f"invalid PostgreSQL version: {version}")
    for distro in distros:
        if not DISTRO_RE.fullmatch(distro):
            raise ReleaseConfigError(f"invalid distro: {distro}")
    if platforms != EXPECTED_PLATFORMS:
        raise ReleaseConfigError(
            f"platforms must be exactly {EXPECTED_PLATFORMS}; build, scan, and verification share this contract"
        )

    publish_jobs = len(postgres_versions) * len(distros)
    validation_jobs = publish_jobs * len(platforms)
    if publish_jobs > GITHUB_MATRIX_MAX_JOBS or validation_jobs > GITHUB_MATRIX_MAX_JOBS:
        raise ReleaseConfigError(
            f"GitHub Actions matrix exceeds {GITHUB_MATRIX_MAX_JOBS} jobs "
            f"(publish={publish_jobs}, validate={validation_jobs})"
        )

    for pg_version, distro in itertools.product(postgres_versions, distros):
        suffix = image_suffix(pg_version, patroni, distro)
        if len(f"main-{suffix}") > OCI_TAG_MAX_LENGTH:
            raise ReleaseConfigError(f"main image tag exceeds {OCI_TAG_MAX_LENGTH} characters: {suffix}")
    return config


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ReleaseConfigError("release config root must be an object")
    return validate_config(config)


def build_matrix(config: dict[str, Any], kind: str) -> dict[str, list[dict[str, str]]]:
    validate_config(config)
    patroni = config["patroni_version"]
    include: list[dict[str, str]] = []
    for pg_version, distro in itertools.product(config["postgres_versions"], config["distros"]):
        base = {
            "pg_version": pg_version,
            "patroni_version": patroni,
            "distro": distro,
        }
        if kind == "publish":
            include.append(base)
        elif kind == "validate":
            for platform in config["platforms"]:
                include.append({**base, "platform": platform})
        else:
            raise ReleaseConfigError(f"unknown matrix kind: {kind}")
    if len(include) > GITHUB_MATRIX_MAX_JOBS:
        raise ReleaseConfigError(f"matrix exceeds {GITHUB_MATRIX_MAX_JOBS} jobs")
    return {"include": include}


def image_suffix(pg_version: str, patroni_version: str, distro: str) -> str:
    return f"{pg_version}-{patroni_version}-{distro}"


def image_suffixes(config: dict[str, Any]) -> list[str]:
    return [
        image_suffix(cell["pg_version"], cell["patroni_version"], cell["distro"])
        for cell in build_matrix(config, "publish")["include"]
    ]


def _release_version_key(tag: str) -> tuple[int, int, int, int, int] | None:
    match = RELEASE_TAG_RE.fullmatch(tag)
    if not match:
        return None
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    stage = match.group("stage")
    stage_rank = {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage]
    number = int(match.group("number") or 0)
    return major, minor, patch, stage_rank, number


def validate_release_tag(tag: str, config: dict[str, Any] | None = None) -> str:
    key = _release_version_key(tag)
    if key is None:
        raise ReleaseConfigError(
            "release tag must be vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-(alpha|beta|rc).N"
        )
    if key[0] < RELEASE_EPOCH_MAJOR:
        raise ReleaseConfigError(f"new release contract starts at v{RELEASE_EPOCH_MAJOR}.0.0")
    if config is not None:
        validate_config(config)
        for suffix in image_suffixes(config):
            final_tag = f"{tag}-{suffix}"
            if len(final_tag) > OCI_TAG_MAX_LENGTH:
                raise ReleaseConfigError(
                    f"image tag exceeds OCI/Docker limit of {OCI_TAG_MAX_LENGTH} characters: {final_tag}"
                )
    return tag


def validate_release_order(tag: str, existing_tags: Iterable[str]) -> str:
    new_key = _release_version_key(tag)
    if new_key is None or new_key[0] < RELEASE_EPOCH_MAJOR:
        raise ReleaseConfigError("new tag is outside the v5+ release contract")
    existing_keys = [
        key
        for existing in existing_tags
        if (key := _release_version_key(existing)) is not None and key[0] >= RELEASE_EPOCH_MAJOR
    ]
    if existing_keys and new_key <= max(existing_keys):
        raise ReleaseConfigError("release tag must be newer than every existing v5+ release tag")
    return tag


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ReleaseConfigError(f"{field} must be a sha256 digest")
    return value


def _require_platform_digests(value: object, field: str, platforms: list[str]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(platforms):
        raise ReleaseConfigError(f"{field} platform set must be exactly {platforms}")
    return {platform: _require_digest(value[platform], f"{field}.{platform}") for platform in platforms}


def build_release_manifest(
    *,
    base_tag: str,
    source_sha: str,
    repository: str,
    artifacts: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if base_tag != "main":
        validate_release_tag(base_tag, config)
    if not SHA_RE.fullmatch(source_sha):
        raise ReleaseConfigError("source SHA must be a full lowercase 40-character commit SHA")
    if not REPOSITORY_RE.fullmatch(repository):
        raise ReleaseConfigError("repository must be owner/name")

    expected_cells = build_matrix(config, "publish")["include"]
    expected_keys = {
        (cell["pg_version"], cell["patroni_version"], cell["distro"]): cell
        for cell in expected_cells
    }
    actual_keys = [
        (
            artifact.get("pg_version"),
            artifact.get("patroni_version"),
            artifact.get("distro"),
        )
        for artifact in artifacts
    ]
    if Counter(actual_keys) != Counter(expected_keys.keys()):
        raise ReleaseConfigError("candidate artifacts must cover every configured image exactly once")

    images: list[dict[str, Any]] = []
    for artifact in artifacts:
        key = (
            artifact["pg_version"],
            artifact["patroni_version"],
            artifact["distro"],
        )
        suffix = image_suffix(*key)
        expected_final = f"{base_tag}-{suffix}"
        if artifact.get("final_tag") != expected_final:
            raise ReleaseConfigError(f"final_tag must be {expected_final}")
        candidate_tag = artifact.get("candidate_tag")
        if not isinstance(candidate_tag, str) or not candidate_tag.startswith("candidate-"):
            raise ReleaseConfigError("candidate_tag must use the candidate- prefix")
        if len(candidate_tag) > OCI_TAG_MAX_LENGTH or len(expected_final) > OCI_TAG_MAX_LENGTH:
            raise ReleaseConfigError(f"image tag exceeds {OCI_TAG_MAX_LENGTH} characters")

        ghcr_digest = _require_digest(artifact.get("ghcr_digest"), "ghcr_digest")
        docker_digest = _require_digest(artifact.get("docker_digest"), "docker_digest")
        ghcr_platforms = _require_platform_digests(
            artifact.get("ghcr_platform_digests"), "ghcr_platform_digests", config["platforms"]
        )
        docker_platforms = _require_platform_digests(
            artifact.get("docker_platform_digests"), "docker_platform_digests", config["platforms"]
        )
        if ghcr_platforms != docker_platforms:
            raise ReleaseConfigError("GHCR and Docker Hub platform digests differ for the same build")

        verification = artifact.get("verification")
        if not isinstance(verification, dict):
            raise ReleaseConfigError("verification receipts must be an object")
        for receipt, expected_value in VERIFICATION_RECEIPTS.items():
            if verification.get(receipt) != expected_value:
                raise ReleaseConfigError(f"verification receipt {receipt} must be {expected_value}")

        images.append(
            {
                "pg_version": key[0],
                "patroni_version": key[1],
                "distro": key[2],
                "candidate_tag": candidate_tag,
                "tag": expected_final,
                "ghcr_ref": f"ghcr.io/{repository}:{expected_final}",
                "docker_ref": f"docker.io/{repository}:{expected_final}",
                "ghcr_digest": ghcr_digest,
                "docker_digest": docker_digest,
                "ghcr_platform_digests": ghcr_platforms,
                "docker_platform_digests": docker_platforms,
                "verification": {receipt: verification[receipt] for receipt in VERIFICATION_RECEIPTS},
            }
        )

    images.sort(key=lambda item: (item["pg_version"], item["distro"]))
    return {
        "schema_version": 1,
        "release": base_tag,
        "source": {
            "repository": repository,
            "commit": source_sha,
            "url": f"https://github.com/{repository}/commit/{source_sha}",
        },
        "platforms": list(config["platforms"]),
        "images": images,
    }


def release_title(release_tag: str, config: dict[str, Any]) -> str:
    validate_release_tag(release_tag, config)
    postgres = " / ".join(config["postgres_versions"])
    return f"{release_tag} · Patroni {config['patroni_version']} · PostgreSQL {postgres}"


def render_release_notes(*, manifest: dict[str, Any], changes: str) -> str:
    release_tag = manifest["release"]
    repository = manifest["source"]["repository"]
    source_sha = manifest["source"]["commit"]
    artifacts = manifest["images"]
    platforms = manifest["platforms"]
    patroni_versions = sorted({artifact["patroni_version"] for artifact in artifacts})
    postgres_versions = sorted({artifact["pg_version"] for artifact in artifacts})
    distros = sorted({artifact["distro"] for artifact in artifacts})
    platform_summary = " and ".join(f"PostgreSQL {version}" for version in postgres_versions)
    patroni_summary = " / ".join(patroni_versions)
    platform_text = ", ".join(f"`{platform}`" for platform in platforms)
    first = artifacts[0]
    identity = (
        f"https://github.com/{repository}/.github/workflows/"
        f"docker.yaml@refs/tags/{release_tag}"
    )

    lines = [
        f"# Patroni Docker {release_tag}",
        "",
        "> A tested, signed multi-platform release promoted by immutable digest from one Git tag.",
        "",
        f"Patroni {patroni_summary} for {platform_summary}.",
        "",
        f"**Source:** [`{source_sha}`](https://github.com/{repository}/commit/{source_sha})",
        "",
        "## Release matrix",
        "",
        f"- **Patroni:** {', '.join(f'`{version}`' for version in patroni_versions)}",
        f"- **PostgreSQL:** {', '.join(f'`{version}`' for version in postgres_versions)}",
        f"- **Distributions:** {', '.join(f'`{distro}`' for distro in distros)}",
        f"- **Platforms:** {platform_text}",
        "- **Evidence:** attached `release-manifest.json`",
        "",
        "| PostgreSQL | Distro | GHCR | Docker Hub |",
        "|---|---|---|---|",
    ]
    for artifact in artifacts:
        ghcr_artifact = f"{artifact['ghcr_ref']}@{artifact['ghcr_digest']}"
        docker_artifact = f"{artifact['docker_ref']}@{artifact['docker_digest']}"
        lines.append(
            f"| `{artifact['pg_version']}` | `{artifact['distro']}` | "
            f"`{ghcr_artifact}` | `{docker_artifact}` |"
        )

    lines.extend(
        [
            "",
            "## Pull",
            "",
            "```bash",
            f"docker pull {first['ghcr_ref']}",
            f"docker pull {first['docker_ref']}",
            "```",
            "",
            "Use a digest-qualified reference from the table for immutable deployments.",
            "",
            "## Verify",
            "",
            "Every index contains the platforms listed above, carries an OCI SBOM and BuildKit provenance, and is keylessly signed in both registries.",
            "",
            "```bash",
            "cosign verify \\",
            f"  --certificate-identity '{identity}' \\",
            "  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \\",
            f"  {first['ghcr_ref']}@{first['ghcr_digest']}",
            "",
            f"gh attestation verify oci://{first['ghcr_ref']} \\",
            f"  --repo {repository}",
            "```",
            "",
            "The same cosign command works for Docker Hub by substituting its registry-qualified digest from the table.",
            "",
            changes.strip() or "## Changes\n\nNo generated change summary was available.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_candidate_artifacts(directory: Path) -> list[dict[str, Any]]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ReleaseConfigError(f"no candidate metadata found in {directory}")
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ReleaseConfigError(f"candidate metadata must be an object: {path}")
        artifacts.append(value)
    return artifacts


def compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    matrix = subparsers.add_parser("matrix")
    matrix.add_argument("--kind", choices=("validate", "publish"), required=True)

    validate_tag = subparsers.add_parser("validate-tag")
    validate_tag.add_argument("tag")
    validate_tag.add_argument("--existing-tags", type=Path)

    subparsers.add_parser("suffixes")
    platforms = subparsers.add_parser("platforms")
    platforms.add_argument("--format", choices=("lines", "csv", "json"), default="lines")

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--base-tag", required=True)
    manifest.add_argument("--source-sha", required=True)
    manifest.add_argument("--repository", required=True)
    manifest.add_argument("--artifacts-dir", type=Path, required=True)

    notes = subparsers.add_parser("notes")
    notes.add_argument("--manifest", type=Path, required=True)
    notes.add_argument("--changes", type=Path, required=True)

    title = subparsers.add_parser("title")
    title.add_argument("tag")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "matrix":
            print(compact_json(build_matrix(config, args.kind)))
        elif args.command == "validate-tag":
            print(validate_release_tag(args.tag, config))
            if args.existing_tags:
                existing = args.existing_tags.read_text(encoding="utf-8").splitlines()
                validate_release_order(args.tag, existing)
        elif args.command == "suffixes":
            print("\n".join(image_suffixes(config)))
        elif args.command == "platforms":
            if args.format == "json":
                print(compact_json(config["platforms"]))
            elif args.format == "csv":
                print(",".join(config["platforms"]))
            else:
                print("\n".join(config["platforms"]))
        elif args.command == "manifest":
            artifacts = _load_candidate_artifacts(args.artifacts_dir)
            manifest = build_release_manifest(
                base_tag=args.base_tag,
                source_sha=args.source_sha,
                repository=args.repository,
                artifacts=artifacts,
                config=config,
            )
            print(compact_json(manifest))
        elif args.command == "notes":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            changes = args.changes.read_text(encoding="utf-8")
            print(render_release_notes(manifest=manifest, changes=changes))
        elif args.command == "title":
            print(release_title(args.tag, config))
        else:  # pragma: no cover
            parser.error(f"unknown command: {args.command}")
    except (ReleaseConfigError, json.JSONDecodeError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
