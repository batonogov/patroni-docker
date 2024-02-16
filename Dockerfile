FROM postgres:16.2

RUN apt update \
    && apt install -y --no-install-recommends \
        patroni=3.2.2-2.pgdg120+1 \
        python3-psycopg2=2.9.9-1.pgdg120+1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /var/lib/postgresql -p \
    && chown postgres:postgres /var/lib/postgresql \
    && chmod 700 /var/lib/postgresql

USER postgres

ENTRYPOINT /usr/bin/patroni /etc/patroni/config.yml
