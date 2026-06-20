ARG DISTRO=trixie
ARG PG_VERSION=17.10
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
      && apk upgrade --no-cache \
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
      && PG_MAJOR=$(ls /usr/lib/postgresql) \
      && apt-mark hold postgresql-${PG_MAJOR} postgresql-client-${PG_MAJOR} \
      && apt-get upgrade -y \
      && PATRONI_DEB_VERSION=$(apt-cache madison patroni \
           | awk -F'|' '{ gsub(/[ \t]/, "", $2); print $2 }' \
           | grep -m1 "^${PATRONI_VERSION}-" || true) \
      && if [ -z "${PATRONI_DEB_VERSION}" ]; then \
           echo "ERROR: patroni ${PATRONI_VERSION} not found in enabled apt sources" >&2; exit 1; \
         fi \
      && echo "Resolved patroni debian version: ${PATRONI_DEB_VERSION}" \
      && apt install -y --no-install-recommends \
        patroni=${PATRONI_DEB_VERSION} \
        python3-psycopg2 \
      && apt clean all \
      && rm -rf \
        /var/lib/apt/lists/* \
        /var/cache/* ; \
    fi \
    && mkdir -p /var/lib/postgresql \
    && chown postgres:postgres /var/lib/postgresql \
    && chmod 700 /var/lib/postgresql \
    && rm -f /usr/local/bin/gosu

USER postgres

ENTRYPOINT ["/usr/bin/patroni"]
CMD [ "/etc/patroni/config.yml" ]
