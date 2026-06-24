# Lima integration test harness

Run the existing Patroni ansible playbook against three **native arm64
virtual machines** (Apple Virtualization.framework, `vmType: vz`) so the
roles are exercised exactly as on a production host — `systemd` as PID 1,
`docker-ce` installed via `apt`, etcd and Patroni running as systemd units
that launch Docker containers.

> ⚠️ **Non-production.** This harness exists only to test the ansible roles.
> It boots full VMs and is intentionally close to a real deployment, but the
> Lima networking, generated secrets, and single-host Docker setup are not
> suitable for production.

## Prerequisites

- **Lima** (`brew install lima`) with the `user-v2` network configured. A
  working `~/.lima/_config/networks.yaml` already defines it
  (gateway `192.168.104.1`). Verify with `limactl list`.
- **ansible-core** on the host (the playbook uses only builtin modules).
- macOS on Apple Silicon (the VM image is arm64 and runs natively — no
  Rosetta, no QEMU emulation).
- The VM image is **Ubuntu 26.04 LTS** (`resolute`). The Docker CE apt
  repository already publishes a `resolute` suite, so the `docker_install`
  role resolves it automatically via `ansible_distribution_release`.

## Resource footprint

Three VMs, each 2 CPUs / 2 GiB RAM / 15 GiB disk → **~6 CPUs and ~6 GiB RAM**
on the host. Boot takes a few minutes the first time (image download +
`apt-get` inside each guest); subsequent starts are fast.

## Usage

```sh
# 1. Boot the three VMs and generate the ansible inventory.
examples/ansible/tests/lima/scripts/up.sh

# 2. Deploy the cluster with the SAME playbook used in production.
cd examples/ansible
ansible-playbook -i tests/lima/inventory.lima.yaml patroni_postgresql_cluster.yaml

# 3. Verify etcd + Patroni formed a healthy 3-node cluster.
examples/ansible/tests/lima/scripts/verify.sh

# 4. Tear everything down when done.
examples/ansible/tests/lima/scripts/down.sh
```

## How it works

### Architecture

The harness boots three full virtual machines on your Mac and treats them
exactly like production Patroni hosts, then runs the **same ansible playbook**
against them. Each VM is **Ubuntu 26.04 LTS** (codename `resolute`) running
native arm64:

```
 ┌─────────────────────────── macOS host ────────────────────────────┐
 │                                                                   │
 │  ansible-playbook ──SSH──► 127.0.0.1:<port>  (one per VM)         │
 │                                                                   │
 │  ┌── VM patroni-postgresql-01 (vz, aarch64, systemd) ───┐         │
 │  │  docker-ce (apt) • etcd.service • patroni.service    │         │
 │  │  user-v2 IP 192.168.104.11                            │         │
 │  └───────────────────────┬──────────────────────────────┘         │
 │  ┌── VM patroni-postgresql-02 (vz, aarch64, systemd) ───┐         │
 │  │  docker-ce (apt) • etcd.service • patroni.service    │         │
 │  │  user-v2 IP 192.168.104.12                            │         │
 │  └───────────────────────┬──────────────────────────────┘         │
 │  ┌── VM patroni-postgresql-03 (vz, aarch64, systemd) ───┐         │
 │  │  docker-ce (apt) • etcd.service • patroni.service    │         │
 │  │  user-v2 IP 192.168.104.13                            │         │
 │  └───────────────────────┬──────────────────────────────┘         │
 │              VMs talk to each other over the user-v2               │
 │              network (192.168.104.0/24, .internal DNS)             │
 └───────────────────────────────────────────────────────────────────┘
```

### Native virtualization (no emulation)

Every VM uses `vmType: vz` — Apple's Virtualization.framework (HVF). Because
the host is Apple Silicon and the image is `aarch64`, the guest CPU runs
**natively**: no QEMU translation, no Rosetta. The Patroni/Postgres container
image (`linux/arm64`) runs at full speed. This is as close to a real Ubuntu
server as a Mac can get.

### systemd as PID 1

The roles manage etcd and Patroni through **systemd unit files**
(`ansible.builtin.systemd` with `daemon_reload`, `enable`, `start`). Plain
containers would not exercise this code path. A Lima VM ships with systemd as
init, giving the roles the same environment as a production host: `systemctl`,
`journalctl`, and unit dependencies (`Requires=` / `After=`).

### The key mechanism: two separate address planes

Each node needs **two different addresses**, and the harness keeps them
deliberately apart. This is the whole reason the test works at all:

| Plane | Address | Used for |
|---|---|---|
| **Management** | `127.0.0.1:<forwarded-port>` | Ansible SSHing from the Mac host |
| **Cluster (advertise)** | `192.168.104.x` (user-v2) | etcd peers & Patroni API reaching each other |

`up.sh` discovers **both** for every VM and writes them into
`inventory.lima.yaml`:

- `ansible_host: 127.0.0.1` / `ansible_port: <port>` — the SSH transport.
- `patroni_node_address: 192.168.104.x` — the address the templates inject
  into `--initial-advertise-peer-urls`, `--advertise-client-urls` and the
  `--add-host` entries.

`patroni_node_address` is an **optional** per-host var added to the templates
for this purpose. When it is absent — as in the production inventory — the
templates fall back to `ansible_host`, so production behaviour is unchanged.

### Why this is "like production"

The roles deployed to these VMs are byte-for-byte the ones that deploy to real
servers. The only differences are the hypervisor and the network addresses;
the systemd units, the docker installation method (`apt install docker-ce`),
the container images, and the Patroni/etcd configuration are identical. A
regression caught here would bite a real deployment too.

### Files

| File | Purpose |
|---|---|
| `lima-node.yaml` | Base Lima config for one node. Booted three times with `--name=` to get `patroni-postgresql-0{1,2,3}`. |
| `scripts/up.sh` | Creates/starts the 3 VMs, waits for their `user-v2` IPs, discovers the forwarded SSH ports, and writes `inventory.lima.yaml`. |
| `scripts/verify.sh` | Runs `etcdctl endpoint status` and `patronictl list` inside the leader VM and asserts: etcd has 3 members with exactly 1 leader; Patroni has 1 Leader (`running`) + 2 Replicas (`streaming`). |
| `scripts/down.sh` | Deletes the 3 VMs and removes the generated inventory. |
| `inventory.lima.yaml.example` | Committed sample showing the generated inventory shape. The real `inventory.lima.yaml` is generated at runtime and is git-ignored. |

## Generated inventory

`up.sh` writes `inventory.lima.yaml` next to this README. Each host entry
connects over SSH through a forwarded `127.0.0.1:<port>` address, while
`patroni_node_address` carries the VM's `user-v2` IP (`192.168.104.x`) that
etcd and Patroni advertise to the rest of the cluster.

## Container image tag

The Patroni Docker image tag comes from
`roles/patroni/vars/main.yml` (`image_version`). The VMs pull it from
`ghcr.io` on first deploy, so no local build is needed.
