# Patroni-Docker

## Overview

**Patroni-Docker** is a project aimed at simplifying the deployment and management of a **PostgreSQL high-availability cluster** using **Patroni** within **Docker** containers.
**Patroni** is a template for **PostgreSQL HA** using Python and ZooKeeper, etcd, or Consul for the coordination and consensus.

Prerequisites:

- **Docker** installed on your system.
- Basic understanding of **Docker** and **PostgreSQL** concepts.

## Examples

### Ansible

For our example, we will take `three nodes` and run `etcd` + `patroni` clusters on them.
We will also configure `haproxy` running on other nodes for `load balancing`.
I deployed with `ansilbe`.

[Ansible example here](./examples/ansible)

### Docker Compose

[Docker Compose example here](./examples/docker)
