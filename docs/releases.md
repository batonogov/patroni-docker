# Releases

This repository treats a release as a verified set of OCI images, not merely a GitHub tag.

## Version contract

Stable Git tags use project SemVer:

```text
vMAJOR.MINOR.PATCH
vMAJOR.MINOR.PATCH-rc.N
```

The project version describes this repository's packaging and delivery contract. Patroni and PostgreSQL keep their own versions and remain explicit in each image tag:

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

Each tag is an OCI index containing `linux/amd64` and `linux/arm64`. The release page records registry-specific immutable digests. No `latest` tag is published because there is no single unambiguous PostgreSQL/distro default.

Existing legacy tags such as `v4.0.5-pg17.5` are retained. They are historical artifacts and are not accepted by the new release-tag validator. The first release using the new multi-image contract should be `v5.0.0` because the artifact and release model changed materially.

## Trust boundaries

The workflow has four distinct phases:

1. **Validate** — every platform, PostgreSQL version, and distro is built, smoke-tested, and scanned. Pull requests cannot publish.
2. **Publish candidates** — only a push to `main` or an accepted release tag can authenticate to registries. One build publishes a multi-platform candidate to both registries with BuildKit SBOM/provenance.
3. **Verify and promote** — exact candidate digests are scanned for both architectures, GHCR provenance is attested, and both registry digests are keylessly signed. Final tags are created only after all candidate jobs pass.
4. **Create the GitHub Release** — a release is created only after every final OCI index contains both supported architectures. Its generated notes include the complete matrix, registry digests, pull commands, and verification commands.

Permissions are granted per job. Pull-request jobs have read-only repository access and never receive registry publishing authority.

## Tag authority and immutability

A stable release can only originate from a Git tag that:

- matches `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCH-{alpha,beta,rc}.N`;
- points to a commit reachable from `main`;
- does not already have a GitHub Release or a final image tag in either registry.

The workflow refuses to overwrite an existing stable tag. A rerun can therefore never silently rebuild `v5.0.0` against newer package mirrors and change its contents.

The registry promotion step starts only after all candidates are tested, scanned, attested, and signed. Promotion spans two external registries and cannot be globally transactional. If infrastructure fails midway through promotion, do not overwrite the version: inspect the partial tags, remove them deliberately if safe, or publish a new patch release.

Repository administrators should also protect `v*` Git tags with a GitHub ruleset and enable immutable GitHub Releases. These are repository settings and cannot be enforced by a pull request.

## Mutable preview channel

A push to `main` updates the compatible `main-<postgres>-<patroni>-<distro>` tags. These are signed preview images, not releases, and may change on every successful `main` build.

`workflow_dispatch` validates the selected ref but intentionally does not publish. Arbitrary manual inputs cannot mint release-looking tags.

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

5. Watch **Build, verify, and release container images**. Do not create a GitHub Release manually; the workflow creates it after successful promotion.
6. Verify at least one image using both the `cosign` and `gh attestation` commands generated on the release page.

## Failure behavior

- A PR failure publishes nothing.
- A `main` failure leaves the previous `main-*` tags intact; run-scoped candidate tags may remain for registry retention cleanup.
- A release candidate failure creates neither final stable tags nor a GitHub Release.
- A promotion failure creates no GitHub Release and requires explicit recovery; the workflow does not overwrite any stable tag.
- Missing Docker Hub credentials fail publication loudly rather than creating a partial two-registry release.
