ARG DISTRO=alpine
FROM postgres:17.6-${DISTRO}

ENV PATRONI_VERSION=4.0.6-1

# Set the package manager and installation commands based on the distro
RUN if [ "${DISTRO}" = "alpine" ]; then \
      apk update \
      && apk add --no-cache \
        patroni=${PATRONI_VERSION} \
        py3-psycopg2; \
      && rm -rf /var/cache/apk/*; \
    else \
      apt update \
      && apt install -y --no-install-recommends \
        patroni=${PATRONI_VERSION} \
        python3-psycopg2 \
      && apt clean all \
      && rm -rf \
        /var/lib/apt/lists/* \
        /var/cache/* ; \
    fi \
    && mkdir -p /var/lib/postgresql \
    && chown postgres:postgres /var/lib/postgresql \
    && chmod 700 /var/lib/postgresql

USER postgres

ENTRYPOINT ["/usr/bin/patroni"]
CMD [ "/etc/patroni/config.yml" ]
