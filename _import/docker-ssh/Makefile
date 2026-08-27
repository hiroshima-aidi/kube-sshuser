SHELL := /bin/bash

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
ROOT_DIR := $(CURDIR)
SSH_DIR := $(ROOT_DIR)/ssh_container

# ---------------------------------------------------------
# Environment (.env)
# ---------------------------------------------------------
ifneq (,$(wildcard .env))
include .env
export GITHUB_USER GITHUB_TOKEN
endif

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
	@echo "  ssh-build          Build SSH container image with Docker"
	@echo "  ssh-buildx         Build with buildx and load to local Docker"
	@echo "  ssh-push           Build with buildx and push to registry"
	@echo "  ssh-import         Import built image into k3s containerd"
	@echo "  ssh-build-import   Build image and import into k3s containerd"
	@echo "  clean              Cleanup build artifacts"
	@echo ""
	@echo "Example:"
	@echo "  make ssh-build IMAGE=docker-ssh:latest"
	@echo "  make ssh-push GITHUB_USER=<user> GITHUB_TOKEN=<token>"
	@echo "  # or put GITHUB_USER / GITHUB_TOKEN in .env"
	@echo "  make ssh-import IMAGE=docker-ssh:latest"
	@echo "  make ssh-build-import IMAGE=docker-ssh:latest"

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
# Cleanup
# ---------------------------------------------------------
.PHONY: clean
clean:
	find $(ROOT_DIR) -type d -name "__pycache__" -prune -exec rm -rf {} +
	find $(ROOT_DIR) -type d -name "*.egg-info" -prune -exec rm -rf {} +
