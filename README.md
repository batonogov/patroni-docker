# Patroni-Docker

## Overview

**Patroni-Docker** is a project aimed at simplifying the deployment and management of a **PostgreSQL high-availability cluster** using **Patroni** within **Docker** containers.
**Patroni** is a template for **PostgreSQL HA** using Python and ZooKeeper, etcd, or Consul for the coordination and consensus.

Prerequisites:

- **Docker** installed on your system.
- Basic understanding of **Docker** and **PostgreSQL** concepts.

## Examples

For our example, we will take `three nodes` and run `etcd` + `patroni` clusters on them.
We will also configure `haproxy` running on other nodes for `load balancing`.
I deployed with `ansilbe`.

### Nodes

```yml
patroni_postgresql_cluster:
  hosts:
    patroni-postgresql-01:
      ansible_host: 10.0.50.10
    patroni-postgresql-02:
      ansible_host: 10.0.50.11
    patroni-postgresql-03:
      ansible_host: 10.0.50.12
```

### Run `etcd` cluster

1. Set the variables

    ```env
    TOKEN: {{ lookup('password', 'secrets/patroni-postgresql/etcd_cluster_token length=64') }}
    CLUSTER: patroni-postgresql-01=http://10.0.50.10:2380,patroni-postgresql-02=http://10.0.50.11:2380,patroni-postgresql-03=http://10.0.50.12:2380
    etcd_version: v3.5.12
    ```

2. Run `etcd` cluster

    ```sh
    /usr/bin/docker run \
        --rm \
        --user {{ patroni_uid }}:{{ patroni_uid }} \
        --publish 2379:2379 \
        --publish 2380:2380 \
        --name etcd \
        --volume=/var/lib/etcd:/etcd-data \
        quay.io/coreos/etcd:{{ etcd_version }} \
        /usr/local/bin/etcd \
        --data-dir=/etcd-data \
        --name {{ inventory_hostname }} \
        --initial-advertise-peer-urls http://{{ ansible_host }}:2380 \
        --listen-peer-urls http://0.0.0.0:2380 \
        --advertise-client-urls http://{{ ansible_host }}:2379 \
        --listen-client-urls http://0.0.0.0:2379 \
        --initial-cluster ${CLUSTER} \
        --initial-cluster-state new \
        --initial-cluster-token ${TOKEN} \
        --enable-v2=true
    ```

3. Check `etcd` cluster status

    ```sh
    docker exec etcd etcdctl endpoint status --write-out=table --cluster

    +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
    |        ENDPOINT        |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS |
    +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
    | http://10.0.50.11:2379 |  4a5b931130e9146 |  3.5.12 |   20 kB |     false |      false |         3 |       8009 |               8009 |        |
    | http://10.0.50.12:2379 |  b54a1c892ce1123 |  3.5.12 |   20 kB |      true |      false |         3 |       8009 |               8009 |        |
    | http://10.0.50.10:2379 | 56ab5b3114566a34 |  3.5.12 |   20 kB |     false |      false |         3 |       8009 |               8009 |        |
    +------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
    ```

### Run `patroni` cluster

1. Prepare **config.yml**

    ```yml
    scope: patroni
    name: {{ inventory_hostname }}

    restapi:
    listen: 0.0.0.0:8008
    connect_address: {{ inventory_hostname }}:8008

    etcd:
    host: {{ inventory_hostname }}:2379

    bootstrap:
    # this section will be written into Etcd:/<namespace>/<scope>/config after initializing new cluster
    dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576
        postgresql:
        use_pg_rewind: true
        use_slots: true
        parameters:
            wal_level: replica
            hot_standby: "on"
            logging_collector: 'on'
            max_wal_senders: 5
            max_replication_slots: 5
            wal_log_hints: "on"

    # some desired options for 'initdb'
    initdb:  # Note: It needs to be a list (some options need values, others are switches)
    - encoding: UTF8
    - data-checksums

    pg_hba:  # Add following lines to pg_hba.conf after running 'initdb'
    - host replication replicator 10.0.50.0/24 md5
    - host replication replicator 127.0.0.1/32 trust
    - host all all 10.0.50.0/24 md5
    - host all all 0.0.0.0/0 md5

    # Additional script to be launched after initial cluster creation (will be passed the connection URL as parameter)
    # post_init: /usr/local/bin/setup_cluster.sh
    # Some additional users users which needs to be created after initializing new cluster
    users:
        admin:
        password: admin
        options:
            - createrole
            - createdb

    postgresql:
    listen: 0.0.0.0:5432
    connect_address: {{ inventory_hostname }}:5432
    data_dir: "/var/lib/postgresql/patroni/main"
    bin_dir: "/usr/lib/postgresql/16/bin"
    pgpass: /tmp/pgpass0
    authentication:
        replication:
        username: replicator
        password: {{ lookup('password', 'secrets/patroni-postgresql/replicator-password length=64') }}
        superuser:
        username: postgres
        password: {{ lookup('password', 'secrets/patroni-postgresql/postgres-password length=64') }}
    parameters:
        unix_socket_directories: '/var/run/postgresql'

    watchdog:
    mode: off

    tags:
        nofailover: false
        noloadbalance: false
        clonefrom: false
        nosync: false
    ```

2. Set the variables

    ```env
    image_version: v0.2.0-beta
    pg_data_dir: /var/lib/postgresql
    patroni_config_dir: /etc/patroni
    ```

3. Run `patroni` cluster

    ```sh
    /usr/bin/docker run \
        --rm \
        --name patroni \
        --hostname {{ inventory_hostname }} \
        --publish 5432:5432 \
        --publish 8008:8008 \
        --publish 8091:8091 \
        --volume={{ patroni_config_dir }}/config.yml:{{ patroni_config_dir }}/config.yml:ro \
        --volume={{ pg_data_dir }}:{{ pg_data_dir }} \
        ghcr.io/batonogov/patroni-docker:{{ image_version }}
    ```

4. Check `patroni` cluster status

    ```sh
    docker exec patroni patronictl -c /etc/patroni/config.yml list
    + Cluster: patroni (7335802398268055573) ------+---------+---------+----+-----------+
    | Member                | Host                  | Role    | State   | TL | Lag in MB |
    +-----------------------+-----------------------+---------+---------+----+-----------+
    | patroni-postgresql-01 | patroni-postgresql-01 | Leader  | running |  8 |           |
    | patroni-postgresql-02 | patroni-postgresql-02 | Replica | running |  7 |        16 |
    | patroni-postgresql-03 | patroni-postgresql-03 | Replica | running |  7 |        16 |
    +-----------------------+-----------------------+---------+---------+----+-----------+
    ```

### Setup `haproxy`

1. Prepare **config.cfg**

    ```cfg
    global
        maxconn 100

    defaults
        log    global
        mode    tcp
        retries 2
        timeout client 30m
        timeout connect 4s
        timeout server 30m
        timeout check 5s

    listen stats
        mode http
        bind *:7000
        stats enable
        stats uri /

    listen primary
        bind *:5000
        option httpchk OPTIONS /master
        http-check expect status 200
        default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
        server patroni-postgresql-01 patroni-postgresql-01:5432 maxconn 100 check port 8008
        server patroni-postgresql-02 patroni-postgresql-02:5432 maxconn 100 check port 8008
        server patroni-postgresql-03 patroni-postgresql-03:5432 maxconn 100 check port 8008

    listen standbys
        balance roundrobin
        bind *:5001
        option httpchk OPTIONS /replica
        http-check expect status 200
        default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
        server patroni-postgresql-01 patroni-postgresql-01:5432 maxconn 100 check port 8008
        server patroni-postgresql-02 patroni-postgresql-02:5432 maxconn 100 check port 8008
        server patroni-postgresql-03 patroni-postgresql-03:5432 maxconn 100 check port 8008
    ```

2. Check `psql`

```sh
psql -h haproxy_host -p 5000 -U postgres

Password for user postgres:
psql (16.2)
```
