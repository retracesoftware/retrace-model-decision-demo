SHELL := /bin/bash
COMPOSE := docker compose --file compose.yaml
DEMO_UID ?= $(shell id -u)
DEMO_GID ?= $(shell id -g)
DEMO_SOURCE_GIT_SHA ?= $(shell git rev-parse HEAD)
export DEMO_UID
export DEMO_GID
export DEMO_SOURCE_GIT_SHA

.PHONY: run replay-example presentation preflight model build prepare start stop clean demo test lifecycle status logs shell vscode

run: preflight model demo

replay-example: preflight build
	python3 -m scripts.run_replay_example

presentation: replay-example

preflight:
	python3 -m scripts.preflight

model:
	ollama pull qwen3:1.7b

build:
	$(COMPOSE) build --pull

prepare: build
	$(COMPOSE) run --rm --no-deps agent python -m scripts.reset_demo

start:
	$(COMPOSE) up --detach --wait

stop:
	$(COMPOSE) down --remove-orphans

clean:
	$(COMPOSE) down --remove-orphans --volumes
	python3 -m scripts.reset_demo

demo:
	python3 -m scripts.run_demo

test:
	$(COMPOSE) run --rm --no-deps -e OTEL_SDK_DISABLED=true agent sh -lc \
		'ruff check agent worker external_world scripts tests && \
		ruff format --check agent worker external_world scripts tests && \
		python -m pytest -q'

lifecycle: build
	$(COMPOSE) run --rm --no-deps agent \
		python -m scripts.verify_foundry_lifecycle --runs 1

vscode:
	python3 -m scripts.prepare_vscode

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --no-color

shell:
	$(COMPOSE) exec agent bash
