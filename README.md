# Patroni Docker

[![Container workflow](https://github.com/batonogov/patroni-docker/actions/workflows/docker.yaml/badge.svg)](https://github.com/batonogov/patroni-docker/actions/workflows/docker.yaml)
[![GitHub Release](https://img.shields.io/github/v/release/batonogov/patroni-docker)](https://github.com/batonogov/patroni-docker/releases)

Multi-platform container images that run [Patroni](https://github.com/zalando/patroni) with PostgreSQL. Images are published to both [GitHub Container Registry](https://github.com/batonogov/patroni-docker/pkgs/container/patroni-docker) and [Docker Hub](https://hub.docker.com/r/batonogov/patroni-docker).

> The deployments under [`examples/`](examples/) are demonstrations, not production-ready cluster definitions.

## Supported images

The canonical matrix lives in [`.github/release-matrix.json`](.github/release-matrix.json). Each image is available for:

- PostgreSQL `17.10` and `18.4`
- Patroni `4.0.7`
- Debian `trixie` and Alpine
- `linux/amd64` and `linux/arm64`

A release tag identifies this repository's delivery version. The complete software tuple remains visible in each image tag:

```text
v<release>-<postgres>-<patroni>-<distro>
# v5.0.0-17.10-4.0.7-trixie
```

`main-*` tags are mutable preview channels. Stable tags are published only from a monotonic project-SemVer Git tag at `v5.0.0` or newer, after every exact candidate digest passes smoke tests and vulnerability scans.

The new workflow never publishes an ambiguous `latest`. A historical GHCR `latest` alias may still be visible for compatibility; it is frozen, deprecated, and must not be used as a release channel. Legacy release tags also remain available and are never repointed.

## Pull an image

Choose PostgreSQL and distro explicitly:

```sh
docker pull ghcr.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie
# or
docker pull docker.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie
```

Each release page contains the complete matrix, immutable registry-specific index digests, and an attached `release-manifest.json` with source SHA, per-platform digests, and verification receipts. Until the first v5 release exists, use `main-*` only for evaluation.

The image entrypoint is Patroni:

```sh
docker run --rm IMAGE patroni --version
docker run --rm --entrypoint /bin/sh IMAGE -c 'postgres --version'
```

## Verify a release

Release images are keylessly signed with Sigstore in both registries. GHCR images also carry GitHub build provenance; BuildKit publishes OCI SBOM and provenance attestations.

Use the complete digest and identity shown on the release page:

```sh
cosign verify \
  --certificate-identity 'https://github.com/batonogov/patroni-docker/.github/workflows/docker.yaml@refs/tags/v5.0.0' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie@sha256:...

gh attestation verify \
  oci://ghcr.io/batonogov/patroni-docker:v5.0.0-17.10-4.0.7-trixie \
  --repo batonogov/patroni-docker
```

## Examples

### Ansible

The [Ansible example](examples/ansible/) deploys etcd, Patroni, and HAProxy across three nodes.

### Docker Compose

The [Docker Compose example](examples/docker/) starts a local three-node etcd and Patroni cluster with HAProxy.

## Release process

See [`docs/releases.md`](docs/releases.md) for the version contract, digest-closed state machine, failure behavior, and maintainer runbook.
