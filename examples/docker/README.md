# Examples

## Docker Compose

A simple example of running a **patroni cluster** in **docker compose**.
**Do not use this example for production.**

Start example project:

```sh
docker compose up --detach --quiet-pull --wait
```

Test **psql** connection:

```sh
psql -h localhost -p 5432 -U postgres
Password for user postgres:
psql (17.2, server 17.1 (Debian 17.1-1.pgdg120+1))
```

Open [localhost:8080](http://localhost:8080) and see **HAProxy Statistics Report**:

![haproxy.png](./haproxy.png)
