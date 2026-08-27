# ---------------------------------------------------------
# builder
# ---------------------------------------------------------
FROM debian:bookworm-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
# The whole packages/ tree, not just this one package: from Phase 3 the shared
# kubelab_core is built into the same venv, and that is the reason these live in
# one repository at all.
COPY packages/ /build/packages/

RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip build && \
    /opt/venv/bin/python -m build --wheel --outdir /build/dist packages/kube_lab

# ---------------------------------------------------------
# final
# ---------------------------------------------------------
FROM debian:bookworm-slim

RUN echo '#!/bin/sh\nexit 101' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    bash \
    jq \
    less \
    vim \
    git \
    procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN rm -f /usr/sbin/policy-rc.d

RUN curl -fsSL -o /usr/local/bin/kubectl https://dl.k8s.io/release/v1.34.1/bin/linux/amd64/kubectl && \
    chown root:root /usr/local/bin/kubectl && \
    chmod 755 /usr/local/bin/kubectl

RUN mkdir -p /var/run/sshd

COPY --from=builder /build/dist/*.whl /tmp/

RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

ENV PATH="/opt/venv/bin:${PATH}"

COPY images/ssh/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV SSH_USER=sshuser
ENV SSH_UID=2000
ENV SSH_GROUP=sshgroup
ENV SSH_GID=2000
ENV SSH_PASSWORD_ENABLED=no
ENV SSH_PASSWORD_VALUE=
ENV SSH_PUBLIC_KEY=

ENV K8S_NAMESPACE=

EXPOSE 22

CMD ["/entrypoint.sh"]