FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS downloader

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/cache-claude-code.sh /usr/local/bin/cache-claude-code
RUN sed -i 's/\r$//' /usr/local/bin/cache-claude-code \
    && chmod 0755 /usr/local/bin/cache-claude-code

ENTRYPOINT ["/usr/local/bin/cache-claude-code", "/cache"]

FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/crates \
    && curl --fail --silent --show-error --location \
        --user-agent symposium-skill-eval-prototype/0.1 \
        https://static.crates.io/crates/cargo-platform/cargo-platform-0.3.3.crate \
        --output /tmp/cargo-platform-0.3.3.crate \
    && echo "dd0061da739915fae12ea00e16397555ed4371a6bb285431aab930f61b0aa4ba  /tmp/cargo-platform-0.3.3.crate" \
        | sha256sum --check - \
    && tar -xzf /tmp/cargo-platform-0.3.3.crate -C /opt/crates \
    && rm /tmp/cargo-platform-0.3.3.crate

COPY bin/cargo /usr/local/bin/cargo
COPY bin/cargo-agents /usr/local/bin/cargo-agents
RUN sed -i 's/\r$//' /usr/local/bin/cargo /usr/local/bin/cargo-agents \
    && chmod 0755 /usr/local/bin/cargo /usr/local/bin/cargo-agents

RUN useradd --create-home --uid 1000 agent \
    && mkdir -p /workspace \
    && chown agent:agent /workspace

USER agent
WORKDIR /workspace
