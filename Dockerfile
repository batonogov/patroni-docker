FROM postgres:16.2

RUN apt update \
    && apt install -y \
        patroni=3.2.2-2.pgdg120+1 \
        python3-psycopg2=2.9.9-1.pgdg120+1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /data/patroni -p \
    && chown postgres:postgres /data/patroni \
    && chmod 700 /data/patroni

COPY ./patroni-entrypoint.sh ./entrypoint.sh
USER postgres

ENTRYPOINT /bin/sh /entrypoint.sh
