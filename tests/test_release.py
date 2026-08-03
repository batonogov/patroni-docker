from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def candidate_artifacts(config: dict[str, object], base_tag: str = "v5.0.0") -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    for index, cell in enumerate(release.build_matrix(config, kind="publish")["include"]):
        suffix = release.image_suffix(
            cell["pg_version"], cell["patroni_version"], cell["distro"]
        )
        child_digest = "sha256:" + f"{index + 1:x}" * 64
        artifacts.append(
            {
                **cell,
                "candidate_tag": f"candidate-123-1-{suffix}",
                "final_tag": f"{base_tag}-{suffix}",
                "ghcr_digest": "sha256:" + f"{index + 5:x}" * 64,
                "docker_digest": "sha256:" + f"{index + 9:x}" * 64,
                "ghcr_platform_digests": {
                    "linux/amd64": child_digest,
                    "linux/arm64": child_digest,
                },
                "docker_platform_digests": {
                    "linux/amd64": child_digest,
                    "linux/arm64": child_digest,
                },
                "verification": {
                    "smoke": "passed",
                    "trivy": "passed",
                    "sbom": "attached",
                    "buildkit_provenance": "attached",
                    "github_provenance": "attested",
                    "ghcr_signature": "signed",
                    "docker_signature": "signed",
                },
            }
        )
    return artifacts


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

    def test_platform_contract_is_exact(self) -> None:
        invalid = deepcopy(self.config)
        invalid["platforms"] = ["linux/amd64"]

        with self.assertRaisesRegex(ValueError, "exactly"):
            release.validate_config(invalid)

    def test_validation_matrix_cannot_exceed_github_limit(self) -> None:
        invalid = deepcopy(self.config)
        invalid["postgres_versions"] = [f"{major}.0" for major in range(1, 130)]

        with self.assertRaisesRegex(ValueError, "256"):
            release.validate_config(invalid)

    def test_duplicate_matrix_values_are_rejected(self) -> None:
        invalid = deepcopy(self.config)
        invalid["postgres_versions"] = ["17.10", "17.10"]

        with self.assertRaisesRegex(ValueError, "duplicate"):
            release.validate_config(invalid)

    def test_image_suffix_preserves_existing_main_tag_contract(self) -> None:
        self.assertEqual(
            release.image_suffix("17.10", "4.0.7", "trixie"),
            "17.10-4.0.7-trixie",
        )


class ReleaseTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = release.load_config(ROOT / ".github" / "release-matrix.json")

    def test_stable_and_release_candidate_tags_are_accepted(self) -> None:
        for tag in ("v5.0.0", "v5.1.0-rc.1"):
            with self.subTest(tag=tag):
                self.assertEqual(release.validate_release_tag(tag, self.config), tag)

    def test_legacy_and_pre_epoch_tags_are_rejected(self) -> None:
        for tag in (
            "v4.0.5-pg17.5",
            "v4.9.9",
            "5.0.0",
            "v05.0.0",
            "v5.0",
            "v5.0.0+build.1",
            "latest",
        ):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    release.validate_release_tag(tag, self.config)

    def test_release_tag_cannot_overflow_oci_variant_tag(self) -> None:
        tag = "v5.0.0-rc." + "1" * 120

        with self.assertRaisesRegex(ValueError, "128"):
            release.validate_release_tag(tag, self.config)

    def test_release_version_must_move_forward(self) -> None:
        release.validate_release_order("v5.1.0-rc.1", ["v5.0.0", "v4.0.5-pg17.5"])

        with self.assertRaisesRegex(ValueError, "newer"):
            release.validate_release_order("v5.0.0-rc.1", ["v5.0.0"])


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = release.load_config(ROOT / ".github" / "release-matrix.json")
        self.artifacts = candidate_artifacts(self.config)

    def build_manifest(self, artifacts: list[dict[str, object]]) -> dict[str, object]:
        return release.build_release_manifest(
            base_tag="v5.0.0",
            source_sha="a" * 40,
            repository="batonogov/patroni-docker",
            artifacts=artifacts,
            config=self.config,
        )

    def test_manifest_closes_source_matrix_and_verification_evidence(self) -> None:
        manifest = self.build_manifest(self.artifacts)

        self.assertEqual(manifest["source"]["commit"], "a" * 40)
        self.assertEqual(manifest["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(len(manifest["images"]), 4)
        self.assertEqual(manifest["images"][0]["verification"]["trivy"], "passed")
        self.assertEqual(
            set(manifest["images"][0]["ghcr_platform_digests"]),
            {"linux/amd64", "linux/arm64"},
        )

    def test_manifest_rejects_missing_or_duplicate_variants(self) -> None:
        for artifacts in (self.artifacts[:-1], [*self.artifacts, self.artifacts[0]]):
            with self.subTest(count=len(artifacts)):
                with self.assertRaisesRegex(ValueError, "exactly once"):
                    self.build_manifest(artifacts)

    def test_manifest_rejects_tag_or_platform_digest_drift(self) -> None:
        invalid_tag = deepcopy(self.artifacts)
        invalid_tag[0]["final_tag"] = "v5.0.0-wrong"
        with self.assertRaisesRegex(ValueError, "final_tag"):
            self.build_manifest(invalid_tag)

        invalid_platforms = deepcopy(self.artifacts)
        del invalid_platforms[0]["docker_platform_digests"]["linux/arm64"]
        with self.assertRaisesRegex(ValueError, "platform"):
            self.build_manifest(invalid_platforms)


class ReleaseCliSecurityTests(unittest.TestCase):
    def test_cli_does_not_delegate_filesystem_authority_to_arguments(self) -> None:
        def option_strings(parser: argparse.ArgumentParser) -> set[str]:
            options: set[str] = set()
            for action in parser._actions:
                options.update(action.option_strings)
                if isinstance(action, argparse._SubParsersAction):
                    for subparser in action.choices.values():
                        options.update(option_strings(subparser))
            return options

        options = option_strings(release._build_parser())

        self.assertTrue(
            {"--config", "--existing-tags", "--artifacts-dir", "--manifest", "--changes"}.isdisjoint(
                options
            )
        )
        self.assertIn("--existing-tags-stdin", options)

    def test_validate_tag_reads_existing_versions_from_stdin(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), mock.patch.object(
            release.sys, "stdin", io.StringIO("v4.0.5-pg17.5\nv5.0.0\n")
        ):
            result = release.main(["validate-tag", "v5.1.0-rc.1", "--existing-tags-stdin"])

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "v5.1.0-rc.1\n")


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github" / "workflows" / "docker.yaml").read_text(
            encoding="utf-8"
        )

    def test_tag_ancestry_precedes_repository_controlled_helper(self) -> None:
        ancestry = self.workflow.index("git merge-base --is-ancestor")
        first_helper = self.workflow.index("python3 scripts/release.py")
        self.assertLess(ancestry, first_helper)

    def test_promotion_consumes_closed_digests_not_candidate_tags(self) -> None:
        promote = self.workflow.split("\n  promote:\n", 1)[1].split(
            "\n  github_release:\n", 1
        )[0]
        self.assertIn('"ghcr.io/${IMAGE_NAME}@${ghcr_digest}"', promote)
        self.assertIn('"docker.io/${IMAGE_NAME}@${docker_digest}"', promote)
        self.assertNotIn("steps.names.outputs.candidate", promote)
        self.assertIn("Refusing to overwrite immutable", promote)
        self.assertIn("current_digest", promote)
        self.assertIn("expected_digest", promote)

    def test_untrusted_runs_cannot_seed_setup_tool_caches(self) -> None:
        self.assertNotIn("cache: true", self.workflow)
        self.assertEqual(self.workflow.count("cache-image: false"), 2)
        self.assertEqual(self.workflow.count("cache-binary: false"), 3)


class ReleaseNotesTests(unittest.TestCase):
    def test_notes_include_source_artifacts_digests_and_verification(self) -> None:
        config = release.load_config(ROOT / ".github" / "release-matrix.json")
        manifest = release.build_release_manifest(
            base_tag="v5.0.0",
            source_sha="a" * 40,
            repository="batonogov/patroni-docker",
            artifacts=candidate_artifacts(config),
            config=config,
        )

        notes = release.render_release_notes(
            manifest=manifest,
            changes="## What's Changed\n\n* Safer releases (#123)",
        )

        self.assertIn("Patroni Docker v5.0.0", notes)
        self.assertIn("PostgreSQL 17.10", notes)
        self.assertIn("PostgreSQL 18.4", notes)
        self.assertIn("linux/amd64", notes)
        self.assertIn("batonogov/patroni-docker/commit/" + "a" * 40, notes)
        self.assertIn("ghcr.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie", notes)
        self.assertIn("docker.io/batonogov/patroni-docker:v5.0.0-18.4-4.0.7-alpine", notes)
        self.assertIn("cosign verify", notes)
        self.assertIn("gh attestation verify", notes)
        self.assertIn("release-manifest.json", notes)
        self.assertIn("## What's Changed", notes)


if __name__ == "__main__":
    unittest.main()
