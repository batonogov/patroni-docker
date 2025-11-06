ARG DISTRO
ARG PG_VERSION
FROM postgres:${PG_VERSION}-${DISTRO}

ARG PATRONI_VERSION
ENV PATRONI_VERSION=${PATRONI_VERSION}
ARG DISTRO
ARG GITHUB_REPOSITORY
ARG GITHUB_SHA

LABEL org.opencontainers.image.title="Patroni v.${PATRONI_VERSION} PG v.${PG_VERSION} Docker Image"
LABEL org.opencontainers.image.description="Image is used for running HA cluster Patroni v.${PATRONI_VERSION} with PostgreSQL v.${PG_VERSION}."
LABEL org.opencontainers.image.version="${PG_VERSION}-${PATRONI_VERSION}-${DISTRO}"
LABEL org.opencontainers.image.created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
LABEL org.opencontainers.image.source="https://github.com/${GITHUB_REPOSITORY}"
LABEL org.opencontainers.image.revision="${GITHUB_SHA}"

# Set the package manager and installation commands based on the distro
RUN echo "DISTRO is: ${DISTRO}"  && echo "PATRONI_VERSION is: ${PATRONI_VERSION}" && \
    if [ "${DISTRO}" = "alpine" ]; then \
      apk update \
      && apk add --no-cache \
        musl-locales \
        python3 \
        py3-pip \
        py3-psycopg \
        py3-psycopg-c \
        py3-psycopg2 \
        py3-psutil \
      && pip install --no-cache-dir --break-system-packages \
        "patroni[psycopg2,psycopg3,all]"==${PATRONI_VERSION} \
      && rm -rf /var/cache/apk/*; \
    else \
      apt update \
      && apt install -y --no-install-recommends \
        patroni=${PATRONI_VERSION}-1 \
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
