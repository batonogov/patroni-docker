# Examples

## Ansible

A simple example of running a **patroni cluster** with **ansible**.
**Do not use this example for production.**

Start patroni cluster:

```sh
ansible-playbook patroni_postgresql_cluster.yaml
```

Check **etcd cluster**:

```sh
ssh infra@10.0.70.55 sudo docker exec etcd etcdctl endpoint status --write-out=table --cluster
```

```output
+------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
|        ENDPOINT        |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS |
+------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
| http://10.0.70.57:2379 |  56b74648d375898 |  3.5.16 |   20 kB |      true |      false |         2 |          8 |                  8 |        |
| http://10.0.70.56:2379 | 9642b91134b8c141 |  3.5.16 |   20 kB |     false |      false |         2 |          8 |                  8 |        |
| http://10.0.70.55:2379 | b0768c2b554448c5 |  3.5.16 |   20 kB |     false |      false |         2 |          8 |                  8 |        |
+------------------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+--------+
```

Check **patroni cluster**:

```sh
ssh infra@10.0.70.55 sudo docker exec patroni patronictl -c /etc/patroni/config.yml list
```

```output
+ Cluster: patroni (7425641088211501077) -------+---------+-----------+----+-----------+
| Member                | Host                  | Role    | State     | TL | Lag in MB |
+-----------------------+-----------------------+---------+-----------+----+-----------+
| patroni-postgresql-01 | patroni-postgresql-01 | Replica | streaming |  1 |         0 |
| patroni-postgresql-02 | patroni-postgresql-02 | Leader  | running   |  1 |           |
| patroni-postgresql-03 | patroni-postgresql-03 | Replica | streaming |  1 |         0 |
+-----------------------+-----------------------+---------+-----------+----+-----------+
```

Test **psql** connection:

```sh
psql -h 10.0.70.55 -p 5432 -U postgres
Password for user postgres:
psql (17.2, server 17.1 (Debian 17.1-1.pgdg120+1))
```
