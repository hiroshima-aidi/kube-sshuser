# ---------------------------------------------------------
# builder
# ---------------------------------------------------------
FROM debian:bookworm-slim AS builder

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY ssh_container/ /build/

RUN python3 -m pip install --upgrade pip build && \
    python3 -m build --wheel

# ---------------------------------------------------------
# final
# ---------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    bash \
    jq \
    less \
    vim \
    git \
    procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# kubectl
RUN curl -fsSL -o /usr/local/bin/kubectl https://dl.k8s.io/release/v1.34.1/bin/linux/amd64/kubectl && \
    chmod 750 /usr/local/bin/kubectl

# wheel install
COPY --from=builder /build/dist/*.whl /tmp/
RUN python3 -m pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

# entrypoint
COPY ssh_container/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]