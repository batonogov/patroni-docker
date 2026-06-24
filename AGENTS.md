# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.
Read this before making changes.

## What this is

**patroni-docker** builds and publishes container images that bundle
[Patroni](https://github.com/zalando/patroni) (PostgreSQL HA) on top of the
official `postgres` image. It also ships two **non-production** examples that run
a full 3-node Patroni cluster (etcd DCS + haproxy load balancer).

The repository produces artifacts in two layers:

1. **The image** (`Dockerfile`) — built for a version matrix and pushed to two
   registries by CI.
2. **The examples** (`examples/`) — reference deployments for Ansible and
   Docker Compose. These are documentation, not the shipped product.

## Repository layout

```
Dockerfile                      # Single Dockerfile; builds both alpine and trixie variants
.github/workflows/docker.yaml   # CI: matrix build + push to ghcr.io and docker.io
.github/workflows/autopr.yaml   # Auto-opens a PR when pushing to any non-main branch
.pre-commit-config.yaml         # yaml formatting, whitespace, private-key detection, ansible-lint
.ansible-lint                   # ansible-lint config
examples/ansible/               # 3-node Ansible deployment (roles: docker_install, etcd, patroni)
examples/ansible/tests/lima/    # integration harness: 3 native arm64 Ubuntu VMs via Lima (vz)
examples/docker/                # docker-compose: etcd x3 + patroni x3 + haproxy
```

## The build matrix (the central concept)

Every build is a Cartesian product defined in `.github/workflows/docker.yaml`.
When you change any of these, you change the whole published surface:

| Dimension        | Values                  |
|------------------|-------------------------|
| `platform`       | `linux/amd64`, `linux/arm64` |
| `distro`         | `trixie`, `alpine`      |
| `pg_version`     | `17.10`, `18.4`         |
| `patroni_version`| `4.0.7`                 |

The image tag is built deterministically as:

```
${BASE_TAG}-${pg_version}-${patroni_version}-${distro}   # lowercased
# example on a push to main:  main-17.10-4.0.7-trixie
# example for a tag v1.2.3 :  v1.2.3-17.10-4.0.7-alpine
```

`BASE_TAG` comes from `docker/metadata-action` (branch name, git tag, or PR
ref), or from the manual `workflow_dispatch` `inputs.tag` when set. The full
image ref is `ghcr.io/batonogov/patroni-docker:<tag>` and
`docker.io/batonogov/patroni-docker:<tag>`.

## Building locally

A `.dockerignore` excludes everything except `Dockerfile` (the Dockerfile does
not COPY/ADD any context files), so the build context is a few KB even though
the working tree contains ~200 MB of local Postgres data under
`examples/docker/patroni-data*`.

`DISTRO` (default `trixie`) and `PG_VERSION` (default `17.10`) are optional;
`PATRONI_VERSION` is the only required arg. A bare `docker build .` fails
loudly unless you pass `--build-arg PATRONI_VERSION=…`.

```sh
docker build \
  --build-arg DISTRO=alpine \
  --build-arg PG_VERSION=17.10 \
  --build-arg PATRONI_VERSION=4.0.7 \
  -t patroni-docker:local-alpine-17.10 \
  .
```

Smoke-test that the binaries start. The image's ENTRYPOINT is
`/usr/bin/patroni`, which silently ignores unknown args, so to actually run
`postgres` you must override the entrypoint (the CI `postgres --version` step
does this too — see the CI/CD section):

```sh
docker run --rm patroni-docker:local-alpine-17.10 patroni --version
docker run --rm --entrypoint /bin/sh patroni-docker:local-alpine-17.10 -c 'postgres --version'
```

> Building `linux/arm64` on an amd64 host requires QEMU/binfmt; CI sets that up
> via `docker/setup-qemu-action` (see the landmine about its `if:` condition
> below).

## Dockerfile conventions (two installation paths)

The single `Dockerfile` branches on `DISTRO`:

- **`alpine`** → `apk add musl-locales python3 py3-pip py3-psycopg
  py3-psycopg-c py3-psycopg2 py3-psutil`, then
  `pip install "patroni[psycopg2,psycopg3,all]"==$VERSION`.
  Source of truth for available versions: [PyPI](https://pypi.org/project/patroni/).
- **`trixie`** (Debian) → resolves the exact Debian package version from the
  upstream `PATRONI_VERSION` at build time (`apt-cache madison patroni`), then
  `apt install patroni=<resolved> python3-psycopg2`. The Debian revision
  (`-3~deb13u1`, `-2.pgdg13+1`, …) is **not** hardcoded: `apt` requires an exact
  full-version match and that revision is chosen by the distro maintainer, not
  us. Sources: Debian trixie main **and** the PGDG `trixie-pgdg` repo already
  enabled inside the official `postgres` image.

Both paths: run as the `postgres` user, `ENTRYPOINT ["/usr/bin/patroni"]`,
`CMD ["/etc/patroni/config.yml"]`. Keep the two paths in sync when adding
Python/Postgres dependencies.

**Security hardening (both paths).** Each install path upgrades base-image
packages to clear HIGH/CRITICAL CVEs (gated by the Trivy scan in CI): alpine
runs `apk upgrade --no-cache`; trixie runs `apt-get upgrade -y` but first
`apt-mark hold`s `postgresql-<major>` / `postgresql-client-<major>`, where
`<major>` is the `PG_MAJOR` environment variable already set by the official
`postgres` base image (e.g. `17`). The hold lets the upgrade patch library
CVEs (openssl, gnutls, …) **without bumping the PostgreSQL point release** away
from the matrix-pinned version — the image tag must stay honest. Both paths
also `rm -f /usr/local/bin/gosu`: gosu is a Go binary shipped by the stock
`postgres` image that carries Go-stdlib CVEs, and it is unused here (our
entrypoint is patroni running as the non-root `postgres` user; patroni never
shells out to gosu). Removing it clears those CVEs and shaves ~2 MB.

The pg_version baseline (`17.10`, `18.4`) is chosen so the base image already
contains the PostgreSQL-server CVE fixes; do not let it fall behind the
fixed-in version of any open CVE, or the Trivy gate will fail.

## CI/CD

`.github/workflows/docker.yaml` triggers on push to `main`, tags, PRs to
`main`, and manual `workflow_dispatch` (which accepts an optional `inputs.tag`
to override the base tag). Per matrix cell it:

1. builds the image (`docker/build-push-action`, `load:` on PRs, `push:false`),
2. runs the `patroni --version` + `postgres --version` smoke test **on PRs only**
   (the `postgres` check overrides the patroni ENTRYPOINT via `--entrypoint
   /bin/sh`, otherwise patroni would swallow the arg and it would be a no-op),
3. scans the loaded image with **Trivy** (`HIGH,CRITICAL`, `exit-code: 1`) **on
   PRs only** — this is the vulnerability gate before merge,
4. pushes to `ghcr.io` (always, except PRs) and exposes its digest as
   `steps.push-ghcr.outputs.digest`,
5. pushes to `docker.io` **only if Docker Hub secrets are present**,
6. signs the published GHCR image with **cosign** keyless (OIDC) **on non-PRs**.
   Cosign runs *last*, so a signing failure does not block publication.

**Known limitation:** the Trivy gate runs on **PRs only**. Images published
from `main`/tags are not re-scanned at publish time (the publish path doesn't
load the image into the runner — see landmine #3). So a CVE disclosed *after*
a PR is approved can still ship to the registries; the gate catches what was
present at PR time. Only the GHCR image is signed; Docker Hub images are not.

Registries and the secrets that gate them:

- **ghcr.io** — authenticated with the automatic `GITHUB_TOKEN`. Always publishes
  on main/tag.
- **docker.io** — gated by repository secrets `DOCKERHUB_REGISTRY_USERNAME` and
  `DOCKERHUB_REGISTRY_PASSWORD`. If they are absent the Docker Hub push step is
  skipped silently; this is intentional, not a failure.

The job grants `packages: write` (to push to ghcr) and `id-token: write`
(used for keyless cosign signing of the published image via GitHub OIDC). The
build uses `cache-from/to: type=gha`.

## Examples (reference deployments, not production)

Both examples are explicitly labeled **"Do not use for production."**

- **Docker Compose** (`examples/docker/`): `etcd0-2` + `patroni0-2` + `haproxy`.
  Run from that directory:
  ```sh
  docker compose up --detach --quiet-pull --wait
  ```
  `entrypoint.sh` derives the container IP and exports the Patroni env vars
  (`PATRONI_*`) from `REPLICATION_NAME/PASS`, `SU_NAME/PASS`,
  `POSTGRES_APP_ROLE_PASS`. Postgres data is bind-mounted under
  `./patroni-data{0,1,2}/`; those dirs are gitignored (`patroni-data*` in
  `.gitignore`) and are local runtime artifacts (~200 MB), never committed —
  never `git add -f` them.

- **Ansible** (`examples/ansible/`): targets 3 hosts in `inventory.yaml`, runs
  the `docker_install`, `etcd`, and `patroni` roles.
  ```sh
  ansible-playbook patroni_postgresql_cluster.yaml
  ```
  Task names in the playbook are in Russian; do not "translate" them as part of
  an unrelated change.

  The `docker_install` role adds the Docker CE apt repository via
  `ansible.builtin.deb822_repository` (not the removed-from-26.04 `apt_key`/
  `apt_repository` modules), so it deploys on Ubuntu 20.04 through 26.04
  (`noble`–`resolute`).

  The roles can be tested end-to-end on a Mac via the Lima harness at
  `examples/ansible/tests/lima/` — see its `README.md`. It boots three native
  arm64 Ubuntu 26.04 VMs (`vmType: vz`), runs this playbook against them, and
  asserts etcd + Patroni form a healthy 3-node cluster.

## Linting and formatting

`pre-commit` runs the standard hooks plus `pretty-format-yaml` and `ansible-lint`
v25.5.0; the canonical list lives in `.pre-commit-config.yaml`. Two non-obvious
exclusions: `pretty-format-yaml` skips `examples/ansible/roles/`, and
`check-added-large-files` skips `examples/docker/haproxy.png`.

Wrinkle: ansible-lint does its own file discovery and also reports pre-existing
`yaml[line-length]` / `yaml[empty-lines]` violations in
`.github/workflows/docker.yaml` (those rules are not in `.ansible-lint`'s
`skip_list`). They are cosmetic and do not affect builds.

Before pushing, run `pre-commit run --all-files`.

## Landmines (read before editing)

These are real, verified traps in the current tree:

1. **Trixie Patroni version must exist in apt; the pin is resolved dynamically.**
   The `trixie` branch resolves the exact Debian package version from the
   upstream `PATRONI_VERSION` at build time (`apt-cache madison patroni`), so it
   no longer hardcodes the Debian revision. Consequence: the matrix's
   `PATRONI_VERSION` must be published in **both** PyPI (alpine path) **and** the
   apt sources visible to the `postgres:*-trixie` base image — Debian trixie main
   and/or PGDG `trixie-pgdg`. If the upstream version is absent from apt, the
   build **fails loudly** with `ERROR: patroni <version> not found in enabled
   apt sources` instead of silently installing something else. As of this commit
   the matrix uses `4.0.7` (PyPI ✅, Debian trixie main `4.0.7-3~deb13u1` ✅);
   `4.0.6` is **not** in trixie and was the original cause of the red CI. Before
   bumping, verify with `apt-cache madison patroni` inside the base image and
   cross-check PyPI — a version must exist in **both**. Verified trixie apt
   availability as of this commit (verified by running `apt-cache madison
   patroni` inside `postgres:*-trixie`): `4.0.7` (Debian main), `4.1.0`, `4.1.2`,
   `4.1.3` (PGDG); PyPI additionally has `4.0.6`/`4.0.8`/`4.0.9`/`4.1.1`, which
   are **not** buildable for trixie. So the buildable-for-both set is currently
   `4.0.7, 4.1.0, 4.1.2, 4.1.3`.

2. **The QEMU `if:` condition is buggy.** In `docker.yaml`:
   `if: ${{ matrix.platform }} == 'linux/arm64'` is always truthy, so QEMU is
   installed even on amd64 jobs. Correct form is
   `if: matrix.platform == 'linux/arm64'` (no `${{ }}` around the comparison).

3. **Separate build and push steps.** The workflow builds once (`push:false`),
   then pushes with two more `build-push-action` invocations (ghcr, then Docker
   Hub). Don't "optimize" this into a single `push:` step without confirming the
   PR smoke-test path still works, since `load:` is only set on the first step.

4. **Builds are time-sensitive and not byte-reproducible.** Both install paths
   run an unbounded package upgrade (`apk upgrade` / `apt-get upgrade`) to pull
   the latest security fixes, so the same Dockerfile + args can produce
   different images days apart. Consequence: CI on an **unchanged** commit can
   flip green→red if a new fixable HIGH/CRITICAL CVE appears against a base
   package, or if a fix lands on the mirrors between the PR scan and the
   post-merge build. `ignore-unfixed: true` mitigates (unfixed CVEs don't fail
   the gate) but does not eliminate this. The fix for a red scan is a
   base-image/package bump, not disabling the gate.

## Workflow conventions

- Branch from `main`, open PRs against `main`.
- Pushing to **any non-main branch** auto-opens a PR via `autopr.yaml`
  (`diillson/auto-pull-request`). You do not need to open it manually.
- GitHub Actions versions are kept current by Dependabot. When several
  Dependabot PRs touch `docker.yaml` at once, expect them to conflict with each
  other — squash them into one change rather than merging piecemeal.
- Do not commit secrets. `detect-private-key` runs in pre-commit; registry
  credentials live only in GitHub Actions secrets.

## Things that are out of scope here

- The published images are consumed by the examples; the examples do **not**
  build the image. If an example references an image tag (e.g. in
  `docker-compose.yaml`), it points at an already-published tag and may lag the
  current matrix — that is expected.
- There is no test suite beyond the CI smoke tests and pre-commit.
