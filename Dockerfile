FROM postgres:16.4

ENV PATRONI_VERSION=3.3.0-1.pgdg120+1
ENV PSYCOPG2_VERSION=2.9.9-1.pgdg120+1

RUN apt update \
    && apt install -y --no-install-recommends \
    patroni=${PATRONI_VERSION} \
    python3-psycopg2=${PSYCOPG2_VERSION} \
    && apt clean \
    && rm -rf \
    /var/lib/apt/lists/* \
    /var/cache/* \
    && mkdir /var/lib/postgresql -p \
    && chown postgres:postgres /var/lib/postgresql \
    && chmod 700 /var/lib/postgresql

USER postgres

ENTRYPOINT ["/usr/bin/patroni"]
CMD [ "/etc/patroni/config.yml" ]
