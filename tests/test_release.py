from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = release.load_config(ROOT / ".github" / "release-matrix.json")

    def test_validation_matrix_is_cartesian_product(self) -> None:
        matrix = release.build_matrix(self.config, kind="validate")

        self.assertEqual(len(matrix["include"]), 8)
        self.assertIn(
            {
                "pg_version": "17.10",
                "patroni_version": "4.0.7",
                "distro": "trixie",
                "platform": "linux/arm64",
            },
            matrix["include"],
        )

    def test_publish_matrix_has_one_multi_platform_build_per_image(self) -> None:
        matrix = release.build_matrix(self.config, kind="publish")

        self.assertEqual(len(matrix["include"]), 4)
        self.assertNotIn("platform", matrix["include"][0])

    def test_duplicate_matrix_values_are_rejected(self) -> None:
        invalid = {
            "schema_version": 1,
            "patroni_version": "4.0.7",
            "postgres_versions": ["17.10", "17.10"],
            "distros": ["trixie"],
            "platforms": ["linux/amd64"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate"):
                release.load_config(path)

    def test_image_suffix_preserves_existing_tag_contract(self) -> None:
        self.assertEqual(
            release.image_suffix("17.10", "4.0.7", "trixie"),
            "17.10-4.0.7-trixie",
        )


class ReleaseTagTests(unittest.TestCase):
    def test_stable_and_release_candidate_tags_are_accepted(self) -> None:
        for tag in ("v5.0.0", "v5.1.0-rc.1"):
            with self.subTest(tag=tag):
                self.assertEqual(release.validate_release_tag(tag), tag)

    def test_legacy_and_non_semver_tags_are_rejected(self) -> None:
        for tag in (
            "v4.0.5-pg17.5",
            "5.0.0",
            "v05.0.0",
            "v5.0",
            "v5.0.0+build.1",
            "latest",
        ):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    release.validate_release_tag(tag)


class ReleaseNotesTests(unittest.TestCase):
    def test_notes_include_artifacts_digests_and_verification(self) -> None:
        artifacts = [
            {
                "pg_version": "17.10",
                "patroni_version": "4.0.7",
                "distro": "trixie",
                "tag": "v5.0.0-17.10-4.0.7-trixie",
                "ghcr_digest": "sha256:" + "a" * 64,
                "docker_digest": "sha256:" + "b" * 64,
            },
            {
                "pg_version": "18.4",
                "patroni_version": "4.0.7",
                "distro": "alpine",
                "tag": "v5.0.0-18.4-4.0.7-alpine",
                "ghcr_digest": "sha256:" + "c" * 64,
                "docker_digest": "sha256:" + "d" * 64,
            },
        ]

        notes = release.render_release_notes(
            release_tag="v5.0.0",
            repository="batonogov/patroni-docker",
            artifacts=artifacts,
            changes="## What's Changed\n\n* Safer releases (#123)",
            platforms=["linux/amd64", "linux/arm64"],
        )

        self.assertIn("Patroni Docker v5.0.0", notes)
        self.assertIn("PostgreSQL 17.10", notes)
        self.assertIn("PostgreSQL 18.4", notes)
        self.assertIn("linux/amd64", notes)
        self.assertIn("ghcr.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie", notes)
        self.assertIn("docker.io/batonogov/patroni-docker:v5.0.0-18.4-4.0.7-alpine", notes)
        self.assertIn("sha256:" + "a" * 64, notes)
        self.assertIn("cosign verify", notes)
        self.assertIn("gh attestation verify", notes)
        self.assertIn("## What's Changed", notes)


if __name__ == "__main__":
    unittest.main()
