SHELL := /bin/bash

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
ROOT_DIR := $(CURDIR)
ADMIN_DIR := $(ROOT_DIR)/admin_tool
SSH_DIR := $(ROOT_DIR)/ssh_container

# ---------------------------------------------------------
# Python / venv
# ---------------------------------------------------------
PYTHON ?= python3
VENV ?= $(HOME)/venvs/docker-ssh-admin
VENV_BIN := $(VENV)/bin
PIP := $(VENV_BIN)/pip

# ---------------------------------------------------------
# Docker / containerd
# ---------------------------------------------------------
DOCKER ?= docker
IMAGE ?= docker-ssh:latest
K3S ?= k3s
SUDO ?= sudo

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  venv               Create virtualenv"
	@echo "  admin-install      Install admin_tool into venv"
	@echo "  ssh-build          Build SSH container image with Docker"
	@echo "  ssh-import         Import built image into k3s containerd"
	@echo "  ssh-build-import   Build image and import into k3s containerd"
	@echo "  clean              Cleanup build artifacts"
	@echo "  clean-venv         Remove virtualenv"
	@echo ""
	@echo "Example:"
	@echo "  make admin-install"
	@echo "  make ssh-build IMAGE=docker-ssh:latest"
	@echo "  make ssh-import IMAGE=docker-ssh:latest"
	@echo "  make ssh-build-import IMAGE=docker-ssh:latest"

# ---------------------------------------------------------
# venv / admin tool
# ---------------------------------------------------------
.PHONY: venv
venv:
	test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	$(PIP) install --upgrade pip setuptools wheel

.PHONY: admin-install
admin-install: venv
	cd $(ADMIN_DIR) && "$(PIP)" install -e .

# ---------------------------------------------------------
# SSH container image
# ---------------------------------------------------------
.PHONY: ssh-build
ssh-build:
	$(DOCKER) build -t $(IMAGE) -f $(SSH_DIR)/Dockerfile .

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

.PHONY: clean-venv
clean-venv:
	rm -rf "$(VENV)"