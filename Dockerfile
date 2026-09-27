# Cache-Me-Outside
# Builds this source tree (not the upstream Valkey image) into a small runtime
# image. The process drops to the non-root `valkey` user before the server starts.
# redis-* names are compatibility symlinks installed by the Valkey Makefile.

FROM debian:bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

# distclean drops any host object files that slipped into the build context.
RUN make distclean || true \
    && make -j"$(nproc)" \
    && make install PREFIX=/opt/cmo

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 999 valkey \
    && useradd --system --uid 999 --gid valkey --home-dir /data --shell /usr/sbin/nologin valkey \
    && mkdir -p /data /etc/cache-me-outside \
    && chown valkey:valkey /data \
    && chmod 750 /data

COPY --from=build /opt/cmo/bin/ /usr/local/bin/
COPY deploy/valkey.conf /etc/cache-me-outside/valkey.conf
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY deploy/healthcheck.sh /usr/local/bin/healthcheck.sh

RUN chmod 755 /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh \
    && chmod 644 /etc/cache-me-outside/valkey.conf

LABEL org.opencontainers.image.title="Cache-Me-Outside" \
      org.opencontainers.image.description="GoDesk home-lab cache, a fork of Valkey" \
      org.opencontainers.image.licenses="BSD-3-Clause" \
      org.opencontainers.image.source="https://github.com/GoDeskio/Cache-Me-Outside"

EXPOSE 6379
VOLUME ["/data"]
WORKDIR /data

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=5 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["docker-entrypoint.sh"]
