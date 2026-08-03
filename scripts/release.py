#!/usr/bin/env python3
"""Validate the release matrix and render deterministic release metadata."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".github" / "release-matrix.json"
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
POSTGRES_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
RELEASE_TAG_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:alpha|beta|rc)\.(0|[1-9][0-9]*))?$"
)
DISTRO_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
PLATFORMS = {"linux/amd64", "linux/arm64"}
REQUIRED_KEYS = {
    "schema_version",
    "patroni_version",
    "postgres_versions",
    "distros",
    "platforms",
}


def _require_unique_strings(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{key} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{key} contains a duplicate value")
    return value


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read release config {path}: {error}") from error

    if not isinstance(config, dict):
        raise ValueError("release config must be a JSON object")
    unknown = set(config) - REQUIRED_KEYS
    missing = REQUIRED_KEYS - set(config)
    if unknown or missing:
        raise ValueError(
            f"release config keys mismatch (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    if config["schema_version"] != 1:
        raise ValueError("unsupported release config schema_version")

    patroni = config["patroni_version"]
    if not isinstance(patroni, str) or not VERSION_RE.fullmatch(patroni):
        raise ValueError("patroni_version must be MAJOR.MINOR.PATCH")

    postgres_versions = _require_unique_strings(config, "postgres_versions")
    distros = _require_unique_strings(config, "distros")
    platforms = _require_unique_strings(config, "platforms")

    for version in postgres_versions:
        if not POSTGRES_RE.fullmatch(version):
            raise ValueError(f"invalid PostgreSQL version: {version}")
    for distro in distros:
        if not DISTRO_RE.fullmatch(distro):
            raise ValueError(f"invalid distro: {distro}")
    for platform in platforms:
        if platform not in PLATFORMS:
            raise ValueError(f"unsupported platform: {platform}")

    return config


def build_matrix(config: dict[str, Any], *, kind: str) -> dict[str, list[dict[str, str]]]:
    cells = [
        {
            "pg_version": pg_version,
            "patroni_version": config["patroni_version"],
            "distro": distro,
        }
        for pg_version, distro in itertools.product(
            config["postgres_versions"], config["distros"]
        )
    ]
    if kind == "publish":
        return {"include": cells}
    if kind == "validate":
        return {
            "include": [
                {**cell, "platform": platform}
                for cell, platform in itertools.product(cells, config["platforms"])
            ]
        }
    raise ValueError(f"unknown matrix kind: {kind}")


def validate_release_tag(tag: str) -> str:
    if not RELEASE_TAG_RE.fullmatch(tag):
        raise ValueError(
            "release tag must be vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-{alpha,beta,rc}.N"
        )
    return tag


def image_suffix(pg_version: str, patroni_version: str, distro: str) -> str:
    if not POSTGRES_RE.fullmatch(pg_version):
        raise ValueError(f"invalid PostgreSQL version: {pg_version}")
    if not VERSION_RE.fullmatch(patroni_version):
        raise ValueError(f"invalid Patroni version: {patroni_version}")
    if not DISTRO_RE.fullmatch(distro):
        raise ValueError(f"invalid distro: {distro}")
    return f"{pg_version}-{patroni_version}-{distro}"


def image_suffixes(config: dict[str, Any]) -> list[str]:
    return [
        image_suffix(cell["pg_version"], cell["patroni_version"], cell["distro"])
        for cell in build_matrix(config, kind="publish")["include"]
    ]


def release_title(release_tag: str, config: dict[str, Any]) -> str:
    validate_release_tag(release_tag)
    postgres = " / ".join(config["postgres_versions"])
    return f"{release_tag} · Patroni {config['patroni_version']} · PostgreSQL {postgres}"


def _validate_artifact(artifact: dict[str, Any], release_tag: str) -> None:
    expected_tag = f"{release_tag}-{image_suffix(artifact['pg_version'], artifact['patroni_version'], artifact['distro'])}"
    if artifact.get("tag") != expected_tag:
        raise ValueError(f"unexpected artifact tag: {artifact.get('tag')}")
    for key in ("ghcr_digest", "docker_digest"):
        digest = artifact.get(key)
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError(f"invalid {key} for {expected_tag}")


def render_release_notes(
    *,
    release_tag: str,
    repository: str,
    artifacts: list[dict[str, Any]],
    changes: str,
    platforms: list[str],
) -> str:
    validate_release_tag(release_tag)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    if not artifacts:
        raise ValueError("release notes require at least one artifact")
    for artifact in artifacts:
        _validate_artifact(artifact, release_tag)

    artifacts = sorted(
        artifacts,
        key=lambda item: (item["pg_version"], item["distro"], item["patroni_version"]),
    )
    patroni_versions = sorted({item["patroni_version"] for item in artifacts})
    postgres_versions = sorted({item["pg_version"] for item in artifacts})
    first = artifacts[0]
    ghcr_ref = f"ghcr.io/{repository}:{first['tag']}"
    docker_ref = f"docker.io/{repository}:{first['tag']}"
    identity = (
        f"https://github.com/{repository}/.github/workflows/"
        f"docker.yaml@refs/tags/{release_tag}"
    )

    platform_summary = " and ".join(f"PostgreSQL {version}" for version in postgres_versions)
    patroni_summary = " / ".join(patroni_versions)

    lines = [
        f"# Patroni Docker {release_tag}",
        "",
        "> A tested, signed multi-platform release published from one Git tag.",
        "",
        f"Patroni {patroni_summary} for {platform_summary}.",
        "",
        "## Release matrix",
        "",
        f"- **Patroni:** {', '.join(f'`{version}`' for version in patroni_versions)}",
        f"- **PostgreSQL:** {', '.join(f'`{version}`' for version in postgres_versions)}",
        f"- **Platforms:** {', '.join(f'`{platform}`' for platform in platforms)}",
        "- **Registries:** `ghcr.io` and `docker.io`",
        "",
        "No ambiguous `latest` tag is published. Choose PostgreSQL and distro explicitly.",
        "",
        "## Images",
        "",
        "| PostgreSQL | Distro | GHCR | Docker Hub |",
        "|---|---|---|---|",
    ]
    for artifact in artifacts:
        ghcr_artifact = f"ghcr.io/{repository}:{artifact['tag']}@{artifact['ghcr_digest']}"
        docker_artifact = f"docker.io/{repository}:{artifact['tag']}@{artifact['docker_digest']}"
        lines.append(
            "| "
            f"`{artifact['pg_version']}` | `{artifact['distro']}` | "
            f"`{ghcr_artifact}` | `{docker_artifact}` |"
        )

    lines.extend(
        [
            "",
            "## Pull",
            "",
            "```sh",
            f"docker pull {ghcr_ref}",
            f"docker pull {docker_ref}",
            "```",
            "",
            "## Verify",
            "",
            "Verify the keyless Sigstore signature against this repository and workflow:",
            "",
            "```sh",
            "cosign verify \\",
            f"  --certificate-identity '{identity}' \\",
            "  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \\",
            f"  {ghcr_ref}@{first['ghcr_digest']}",
            "```",
            "",
            "Verify GitHub build provenance for the GHCR image:",
            "",
            "```sh",
            f"gh attestation verify oci://{ghcr_ref} --repo {repository}",
            "```",
            "",
            "Inspect the OCI index and its platform manifests:",
            "",
            "```sh",
            f"docker buildx imagetools inspect {ghcr_ref}",
            "```",
            "",
            changes.strip() or "## What's Changed\n\nNo generated changes were returned by GitHub.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    matrix = subparsers.add_parser("matrix")
    matrix.add_argument("--kind", choices=("validate", "publish"), required=True)

    subparsers.add_parser("suffixes")

    validate_tag = subparsers.add_parser("validate-tag")
    validate_tag.add_argument("tag")

    title = subparsers.add_parser("title")
    title.add_argument("tag")

    notes = subparsers.add_parser("notes")
    notes.add_argument("--tag", required=True)
    notes.add_argument("--repository", required=True)
    notes.add_argument("--artifacts", type=Path, required=True)
    notes.add_argument("--changes", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        config = load_config(args.config)
        if args.command == "matrix":
            print(json.dumps(build_matrix(config, kind=args.kind), separators=(",", ":")))
        elif args.command == "suffixes":
            print("\n".join(image_suffixes(config)))
        elif args.command == "validate-tag":
            print(validate_release_tag(args.tag))
        elif args.command == "title":
            print(release_title(args.tag, config))
        elif args.command == "notes":
            artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
            changes = args.changes.read_text(encoding="utf-8")
            print(
                render_release_notes(
                    release_tag=args.tag,
                    repository=args.repository,
                    artifacts=artifacts,
                    changes=changes,
                    platforms=config["platforms"],
                ),
                end="",
            )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"release.py: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
