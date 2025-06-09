FROM postgres:17.3

ENV PATRONI_VERSION=4.0.5-1.pgdg120+1

RUN apt update \
    && apt install -y --no-install-recommends \
    patroni=${PATRONI_VERSION} \
    python3-psycopg2 \
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
