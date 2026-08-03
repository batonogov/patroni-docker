# Releases

This repository treats a release as a verified set of OCI images, not merely a GitHub tag.

## Version contract

Stable Git tags use project SemVer:

```text
vMAJOR.MINOR.PATCH
vMAJOR.MINOR.PATCH-{alpha,beta,rc}.N
```

The v5 epoch describes this repository's packaging and delivery contract. Patroni and PostgreSQL keep their own versions and remain explicit in each image tag:

```text
<project-release>-<postgres>-<patroni>-<distro>
```

For example, Git tag `v5.0.0` produces:

```text
v5.0.0-17.10-4.0.7-trixie
v5.0.0-17.10-4.0.7-alpine
v5.0.0-18.4-4.0.7-trixie
v5.0.0-18.4-4.0.7-alpine
```

The validator requires `v5.0.0` or newer, rejects versions that do not move forward from existing v5 tags, and rejects any final image tag longer than the OCI/Docker 128-character limit.

Each stable tag is an OCI index containing exactly `linux/amd64` and `linux/arm64`. The release page records registry-specific index digests and attaches `release-manifest.json` with source commit, per-platform manifest digests, and verification receipts.

The workflow never creates or repoints `latest`. A historical GHCR `latest` alias may remain visible; it is frozen and deprecated. Existing release tags such as `v4.0.5-pg17.5` are also retained as historical artifacts and are not accepted by the v5 validator.

## Digest-closed state machine

The workflow has five trust phases:

1. **Validate** — every platform, PostgreSQL version, and distro is built, smoke-tested, and scanned. Pull requests cannot publish.
2. **Publish candidates** — only a push to `main` or an accepted release tag can authenticate to registries. One Buildx invocation publishes the same multi-platform candidate build to both registries.
3. **Close evidence** — the workflow resolves both registry indexes to digests, requires their exact runnable platform sets and child digests to match, smoke-tests and scans every exact GHCR platform digest, attaches SBOM/provenance, attests GHCR, and signs both registry-specific index digests.
4. **Promote by digest** — candidate evidence is handed to the promotion job through short-lived workflow artifacts. Promotion consumes `repository@sha256:...`, never a mutable candidate tag. It accepts an existing stable tag only when it already equals the expected digest, which makes a partial promotion safely resumable.
5. **Release last** — final refs are re-inspected, signatures and GHCR provenance are verified against final digests, the complete machine manifest is preserved, and only then is the GitHub Release created.

Permissions are granted per job. Pull-request and manual-dispatch jobs have read-only repository access and never receive registry credentials. Actions, Buildx, BuildKit, binfmt, Trivy, and cosign versions are pinned; shared setup caches are disabled so an untrusted PR cannot seed release tooling.

## Tag authority and immutability

A stable release can originate only from a Git tag that:

- matches the v5+ project-SemVer grammar;
- is newer than every existing v5 project release tag;
- keeps every generated OCI tag within 128 characters;
- points to a commit reachable from `main`;
- does not already have a GitHub Release.

Immediately before each stable final write, promotion applies this rule:

- final ref absent → create it from the closed digest;
- final ref already equals the closed digest → no-op and resume;
- final ref points elsewhere → hard fail; never overwrite it.

OCI registries do not provide one transaction spanning GHCR and Docker Hub. The workflow therefore starts promotion only after all candidates pass and makes each write idempotent. Repository administrators should additionally protect `v*` Git tags with a GitHub ruleset, enable immutable GitHub Releases, and enable registry tag immutability where available. These are repository settings and cannot be enforced by a pull request.

## Rebuild reproducibility

A published release is immutable by digest and is built once before promotion to both registries. A later rebuild of the same source is **not** expected to be byte-identical: both Dockerfile paths intentionally consume current security updates from package mirrors. SBOM and provenance describe the exact release that was built; a security rebuild receives a new project version.

## Mutable preview channel

A push to `main` updates the compatible `main-<postgres>-<patroni>-<distro>` tags. They are signed preview images, not releases, and may change on every successful `main` build.

`workflow_dispatch` validates the selected ref but intentionally cannot access publishing credentials or publish images. Arbitrary manual runs cannot mint release-looking tags.

## Maintainer runbook

1. Update [`.github/release-matrix.json`](../.github/release-matrix.json) in a pull request.
2. Verify the requested Patroni version exists in both PyPI and the apt sources used by the trixie base image.
3. Merge only after the complete validation matrix is green.
4. Create an annotated tag on the intended `main` commit:

   ```sh
   git switch main
   git pull --ff-only
   git tag -a v5.0.0 -m 'Patroni Docker v5.0.0'
   git push origin v5.0.0
   ```

5. Watch **Build, verify, and release container images**. Do not create a GitHub Release manually; the workflow creates it after successful digest promotion.
6. Download `release-manifest.json` and verify at least one image with both generated `cosign` and `gh attestation` commands.

## Failure and recovery

- A PR or manual validation failure publishes nothing.
- A `main` failure leaves the previous `main-*` tags intact; run-scoped candidate tags may remain for registry retention cleanup.
- A candidate build, smoke, scan, attestation, or signature failure creates no final stable tag and no GitHub Release. Use **Re-run failed jobs** after fixing transient infrastructure.
- If promotion stops midway, use **Re-run failed jobs**, not **Re-run all jobs**. The same closed digest artifacts are reused; matching final tags are no-ops and missing tags are completed.
- If a final tag exists with another digest, stop. Investigate or issue a new patch version; the workflow will not overwrite it.
- If only GitHub Release creation fails, re-run that failed job; already verified images remain unchanged.
- Missing Docker Hub credentials fail publication loudly rather than creating a partial two-registry release.
