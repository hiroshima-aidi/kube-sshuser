SHELL := /bin/bash

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
ROOT_DIR := $(CURDIR)
SSH_DIR := images/ssh
JUPYTER_DIR := images/jupyter

# ---------------------------------------------------------
# Environment (.env)
# ---------------------------------------------------------
ifneq (,$(wildcard .env))
include .env
export GITHUB_USER GITHUB_TOKEN
endif

# ---------------------------------------------------------
# Python
# ---------------------------------------------------------
PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

PACKAGES := packages/kube_sshuser packages/kube_lab packages/kube_jupyterhub

# ---------------------------------------------------------
# Docker / containerd
# ---------------------------------------------------------
DOCKER ?= docker
IMAGE ?= docker-ssh:latest
DOCKER_REGISTRY ?= ghcr.io
IMAGE_NAME_BASE ?= hiroshima-aidi/ssh-for-k8s
IMAGE_TAG ?= latest
PUSH_IMAGE ?= $(DOCKER_REGISTRY)/$(IMAGE_NAME_BASE):$(IMAGE_TAG)
PLATFORM ?= linux/amd64
BUILDX_BUILDER ?= multiarch-builder
K3S ?= k3s
SUDO ?= sudo
GITHUB_USER ?=
GITHUB_TOKEN ?=

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  dev-install        Install all Python packages in editable mode"
	@echo ""
	@echo "  ssh-build          Build SSH container image with Docker"
	@echo "  ssh-buildx         Build with buildx and load to local Docker"
	@echo "  ssh-push           Build with buildx and push to registry"
	@echo "  ssh-import         Import built image into k3s containerd"
	@echo "  ssh-build-import   Build image and import into k3s containerd"
	@echo ""
	@echo "  jupyter-<target>   Delegate to $(JUPYTER_DIR)/Makefile"
	@echo "                     e.g. jupyter-build, jupyter-push, jupyter-push-all"
	@echo "  jupyter-help       Show the Jupyter image targets and their variables"
	@echo ""
	@echo "  clean              Cleanup build artifacts"
	@echo ""
	@echo "Example:"
	@echo "  make dev-install"
	@echo "  make ssh-build IMAGE=docker-ssh:latest"
	@echo "  make ssh-push GITHUB_USER=<user> GITHUB_TOKEN=<token>"
	@echo "  # or put GITHUB_USER / GITHUB_TOKEN in .env"
	@echo "  make ssh-import IMAGE=docker-ssh:latest"
	@echo "  make ssh-build-import IMAGE=docker-ssh:latest"
	@echo "  make jupyter-build STACK=cpu WITH_IJULIA=1"
	@echo "  make jupyter-push STACK=cuda12.2 IMAGE_TAG=2026.04.01"

# ---------------------------------------------------------
# Development install
# ---------------------------------------------------------
.PHONY: dev-install
dev-install:
	$(PIP) install -e packages/kube_sshuser
	$(PIP) install -e packages/kube_lab
	$(PIP) install -e packages/kube_jupyterhub

# ---------------------------------------------------------
# SSH container image
# ---------------------------------------------------------

.PHONY: _buildx-bootstrap
_buildx-bootstrap:
	@if ! $(DOCKER) buildx inspect $(BUILDX_BUILDER) >/dev/null 2>&1; then \
		$(DOCKER) buildx create --name $(BUILDX_BUILDER) --use; \
	else \
		$(DOCKER) buildx use $(BUILDX_BUILDER); \
	fi
	$(DOCKER) buildx inspect --bootstrap


.PHONY: _login
_login:
	@if [ -z "$(GITHUB_USER)" ] || [ -z "$(GITHUB_TOKEN)" ]; then \
		echo "Error: GITHUB_USER and GITHUB_TOKEN must be set"; \
		exit 1; \
	fi
	echo "$(GITHUB_TOKEN)" | $(DOCKER) login $(DOCKER_REGISTRY) -u $(GITHUB_USER) --password-stdin

.PHONY: ssh-build
ssh-build:
	$(DOCKER) build -t $(IMAGE) -f $(SSH_DIR)/Dockerfile .

.PHONY: ssh-buildx
ssh-buildx: _buildx-bootstrap
	$(DOCKER) buildx build \
		--platform $(PLATFORM) \
		-f $(SSH_DIR)/Dockerfile \
		-t $(IMAGE) \
		--load .

.PHONY: ssh-push
ssh-push: _buildx-bootstrap _login
	$(DOCKER) buildx build \
		--platform $(PLATFORM) \
		-f $(SSH_DIR)/Dockerfile \
		-t $(PUSH_IMAGE) \
		--push .

.PHONY: ssh-import
ssh-import:
	$(DOCKER) save $(IMAGE) | $(SUDO) $(K3S) ctr images import -
	$(SUDO) $(K3S) ctr images ls | grep -F "$(IMAGE)"

.PHONY: ssh-build-import
ssh-build-import: ssh-build ssh-import

# ---------------------------------------------------------
# Jupyter image
#
# Delegated rather than merged: those Dockerfiles COPY requirements/ and
# scripts/ relative to the build context, so the context has to stay
# $(JUPYTER_DIR). Running its Makefile from there keeps every command it
# emits byte-identical to the standalone repository.
# ---------------------------------------------------------
.PHONY: jupyter-%
jupyter-%:
	$(MAKE) -C $(JUPYTER_DIR) $*

.PHONY: jupyter-help
jupyter-help:
	$(MAKE) -C $(JUPYTER_DIR) help

# ---------------------------------------------------------
# Cleanup
# ---------------------------------------------------------
.PHONY: clean
clean:
	find $(ROOT_DIR) -type d -name "__pycache__" -prune -exec rm -rf {} +
	find $(ROOT_DIR) -type d -name "*.egg-info" -prune -exec rm -rf {} +
