SHELL := /bin/bash

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
ROOT_DIR := $(CURDIR)

# ---------------------------------------------------------
# Environment (.env)
# ---------------------------------------------------------
ifneq (,$(wildcard .env))
include .env
endif

# ---------------------------------------------------------
# Docker / Build Configuration
# ---------------------------------------------------------
DOCKER ?= docker
IMAGE_NAME ?= jupyter-gpu
IMAGE_TAG ?= 2026.04.01
IMAGE_ORGANIZATION ?= rellab
DOCKER_REGISTRY ?= ghcr.io
DOCKER_USERNAME ?= $(GITHUB_USER)
DOCKER_TOKEN ?= $(GITHUB_TOKEN)
PLATFORM ?= linux/amd64
BUILDX_BUILDER ?= multiarch-builder
PUSH_RETRIES ?= 3

# Stack selection: cpu | cuda12.2 | cuda11.8
STACK ?= cuda12.2
# Enable IJulia kernel install: 1 (enabled) | 0 (disabled)
WITH_IJULIA ?= 1
# Flavor selection: cv | dl
FLAVOR ?= cv

# Fallback to defaults when variables are present but empty.
IMAGE_NAME := $(or $(strip $(IMAGE_NAME)),jupyter-gpu)
IMAGE_ORGANIZATION := $(or $(strip $(IMAGE_ORGANIZATION)),rellab)
DOCKER_REGISTRY := $(or $(strip $(DOCKER_REGISTRY)),ghcr.io)
DOCKER_USERNAME := $(or $(strip $(DOCKER_USERNAME)),$(strip $(GITHUB_USER)))
DOCKER_TOKEN := $(or $(strip $(DOCKER_TOKEN)),$(strip $(GITHUB_TOKEN)))

export DOCKER_USERNAME
export DOCKER_TOKEN

DOCKERFILE_CPU ?= $(ROOT_DIR)/docker/cpu/Dockerfile.cpu-standard
DOCKERFILE_CUDA_12.2 ?= $(ROOT_DIR)/docker/gpu/Dockerfile.cuda12.2-standard
DOCKERFILE_CUDA_11.8 ?= $(ROOT_DIR)/docker/gpu/Dockerfile.cuda11.8-standard
DOCKERFILE := $(if $(filter cpu,$(STACK)),$(DOCKERFILE_CPU),$(if $(filter cuda12.2,$(STACK)),$(DOCKERFILE_CUDA_12.2),$(if $(filter cuda11.8,$(STACK)),$(DOCKERFILE_CUDA_11.8),)))
FLAVOR_DOCKERFILE_CV ?= $(ROOT_DIR)/docker/flavors/Dockerfile.cv
FLAVOR_DOCKERFILE_DL ?= $(ROOT_DIR)/docker/flavors/Dockerfile.dl
FLAVOR_DOCKERFILE := $(if $(filter cv,$(FLAVOR)),$(FLAVOR_DOCKERFILE_CV),$(if $(filter dl,$(FLAVOR)),$(FLAVOR_DOCKERFILE_DL),))

IJULIA_SUFFIX := $(if $(filter 1,$(WITH_IJULIA)),-ijulia,)
LOCAL_IMAGE := $(IMAGE_NAME):$(STACK)$(IJULIA_SUFFIX)
PUSH_IMAGE := $(DOCKER_REGISTRY)/$(IMAGE_ORGANIZATION)/$(IMAGE_NAME):$(STACK)$(IJULIA_SUFFIX)-$(IMAGE_TAG)
FLAVOR_LOCAL_IMAGE := $(IMAGE_NAME):$(STACK)$(IJULIA_SUFFIX)-$(FLAVOR)
FLAVOR_PUSH_IMAGE := $(DOCKER_REGISTRY)/$(IMAGE_ORGANIZATION)/$(IMAGE_NAME):$(STACK)$(IJULIA_SUFFIX)-$(FLAVOR)-$(IMAGE_TAG)

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  build              Build Docker image locally (amd64)"
	@echo "  buildx             Build with buildx and load to local Docker (amd64)"
	@echo "  push               Build with buildx and push to registry (amd64)"
	@echo "  push-all           Build and push CPU, CUDA 12.2 and CUDA 11.8"
	@echo "  build-flavor       Build flavor image locally (BASE_IMAGE from local standard image)"
	@echo "  buildx-flavor      Build flavor image with buildx and load locally"
	@echo "  push-flavor        Build flavor image with buildx and push to registry"
	@echo "  push-flavor-all    Build and push both cv and dl flavor images"
	@echo "  run                Run the container locally"
	@echo "  clean              Cleanup build cache"
	@echo ""
	@echo "Configuration (from .env or environment):"
	@echo "  GITHUB_USER        GitHub username for authentication (from .env)"
	@echo "  GITHUB_TOKEN       GitHub token for authentication (from .env)"
	@echo "  IMAGE_ORGANIZATION Organization name (default: rellab)"
	@echo "  DOCKER_REGISTRY    Docker registry (default: ghcr.io)"
	@echo "  IMAGE_NAME         Image name (default: jupyter-gpu)"
	@echo "  IMAGE_TAG          Image tag suffix (default: 2026.04.01)"
	@echo "  STACK              Stack type (default: cuda12.2, options: cpu | cuda12.2 | cuda11.8)"
	@echo "  WITH_IJULIA        Install IJulia kernel (default: 1, options: 0 | 1)"
	@echo "  FLAVOR             Flavor type (default: cv, options: cv | dl)"
	@echo "  PUSH_RETRIES       Retry count for push on transient network errors (default: 3)"
	@echo ""
	@echo "Examples:"
	@echo "  make build STACK=cpu WITH_IJULIA=1"
	@echo "  make buildx STACK=cuda11.8"
	@echo "  make push STACK=cuda12.2 IMAGE_TAG=2026.04.01"
	@echo "  make push-all"
	@echo "  make build-flavor STACK=cuda12.2 FLAVOR=cv"
	@echo "  make push-flavor STACK=cpu FLAVOR=dl IMAGE_TAG=2026.04.01"

# ---------------------------------------------------------
# Build and Push
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
	@if [ -z "$$DOCKER_USERNAME" ] || [ -z "$$DOCKER_TOKEN" ]; then \
		echo "Error: DOCKER_USERNAME and DOCKER_TOKEN must be set"; \
		exit 1; \
	fi
	@echo "$$DOCKER_TOKEN" | $(DOCKER) login $(DOCKER_REGISTRY) -u "$$DOCKER_USERNAME" --password-stdin

.PHONY: _get-dockerfile
_get-dockerfile:
	@if [ -z "$(DOCKERFILE)" ]; then \
		echo "Error: Unsupported STACK=$(STACK). Supported: cpu cuda12.2 cuda11.8"; \
		exit 1; \
	fi
	@echo $(DOCKERFILE)

.PHONY: _validate-stack
_validate-stack:
	@if [ -z "$(DOCKERFILE)" ]; then \
		echo "Error: Unsupported STACK=$(STACK). Supported: cpu cuda12.2 cuda11.8"; \
		exit 1; \
	fi

.PHONY: _validate-flavor
_validate-flavor:
	@if [ -z "$(FLAVOR_DOCKERFILE)" ]; then \
		echo "Error: Unsupported FLAVOR=$(FLAVOR). Supported: cv dl"; \
		exit 1; \
	fi

.PHONY: build
build: _validate-stack
	$(DOCKER) build \
		--platform $(PLATFORM) \
		-t $(LOCAL_IMAGE) \
		-f $(DOCKERFILE) \
		--build-arg WITH_IJULIA=$(WITH_IJULIA) \
		.

.PHONY: buildx
buildx: _buildx-bootstrap _validate-stack
	$(DOCKER) buildx build \
		--platform $(PLATFORM) \
		-f $(DOCKERFILE) \
		-t $(LOCAL_IMAGE) \
		--build-arg WITH_IJULIA=$(WITH_IJULIA) \
		--load \
		.

.PHONY: push
push: _buildx-bootstrap _login _validate-stack
	@attempt=1; \
	until [ $$attempt -gt $(PUSH_RETRIES) ]; do \
		echo "Push attempt $$attempt/$(PUSH_RETRIES): $(PUSH_IMAGE)"; \
		if $(DOCKER) buildx build \
			--platform $(PLATFORM) \
			-f $(DOCKERFILE) \
			-t $(PUSH_IMAGE) \
			--build-arg WITH_IJULIA=$(WITH_IJULIA) \
			--push \
			.; then \
			exit 0; \
		fi; \
		if [ $$attempt -eq $(PUSH_RETRIES) ]; then \
			echo "Push failed after $(PUSH_RETRIES) attempts"; \
			exit 1; \
		fi; \
		attempt=$$((attempt + 1)); \
	done

.PHONY: push-cpu
push-cpu:
	$(MAKE) push STACK=cpu WITH_IJULIA=1

.PHONY: push-cuda12.2
push-cuda12.2:
	$(MAKE) push STACK=cuda12.2 WITH_IJULIA=1

.PHONY: push-cuda11.8
push-cuda11.8:
	$(MAKE) push STACK=cuda11.8 WITH_IJULIA=1

.PHONY: push-all
push-all: push-cpu push-cuda12.2 push-cuda11.8
	@echo "Successfully pushed CPU, CUDA 12.2 and CUDA 11.8 images"

.PHONY: build-flavor
build-flavor: _validate-stack _validate-flavor
	$(DOCKER) build \
		--platform $(PLATFORM) \
		-f $(FLAVOR_DOCKERFILE) \
		--build-arg BASE_IMAGE=$(LOCAL_IMAGE) \
		-t $(FLAVOR_LOCAL_IMAGE) \
		.

.PHONY: buildx-flavor
buildx-flavor: _buildx-bootstrap _validate-stack _validate-flavor
	$(DOCKER) buildx build \
		--platform $(PLATFORM) \
		-f $(FLAVOR_DOCKERFILE) \
		--build-arg BASE_IMAGE=$(LOCAL_IMAGE) \
		-t $(FLAVOR_LOCAL_IMAGE) \
		--load \
		.

.PHONY: push-flavor
push-flavor: _buildx-bootstrap _login _validate-stack _validate-flavor
	@attempt=1; \
	until [ $$attempt -gt $(PUSH_RETRIES) ]; do \
		echo "Push attempt $$attempt/$(PUSH_RETRIES): $(FLAVOR_PUSH_IMAGE)"; \
		if $(DOCKER) buildx build \
			--platform $(PLATFORM) \
			-f $(FLAVOR_DOCKERFILE) \
			--build-arg BASE_IMAGE=$(PUSH_IMAGE) \
			-t $(FLAVOR_PUSH_IMAGE) \
			--push \
			.; then \
			exit 0; \
		fi; \
		if [ $$attempt -eq $(PUSH_RETRIES) ]; then \
			echo "Push failed after $(PUSH_RETRIES) attempts"; \
			exit 1; \
		fi; \
		attempt=$$((attempt + 1)); \
	done

.PHONY: push-flavor-cv
push-flavor-cv:
	$(MAKE) push-flavor FLAVOR=cv

.PHONY: push-flavor-dl
push-flavor-dl:
	$(MAKE) push-flavor FLAVOR=dl

.PHONY: push-flavor-all
push-flavor-all: push-flavor-cv push-flavor-dl
	@echo "Successfully pushed cv and dl flavor images"

.PHONY: run
run:
	$(DOCKER) run --rm -it \
		-p 8888:8888 \
		$(LOCAL_IMAGE)

# ---------------------------------------------------------
# Cleanup
# ---------------------------------------------------------

.PHONY: clean
clean:
	$(DOCKER) buildx prune -f
