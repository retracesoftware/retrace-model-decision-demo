SHELL := /bin/bash
COMPOSE := docker compose --file compose.yaml
DEMO_UID ?= $(shell id -u)
DEMO_GID ?= $(shell id -g)
DEMO_SOURCE_GIT_SHA ?= $(shell git rev-parse HEAD)
export DEMO_UID
export DEMO_GID
export DEMO_SOURCE_GIT_SHA

.PHONY: run investigate compare replay-pair replay-example show-success show-failure presentation preflight model build prepare start stop clean demo test lifecycle status logs shell vscode vscode-success

run: preflight model demo

investigate:
	@printf '\n%s\n' '=== 1. Prepare and verify the reviewed Retrace recording ==='
	$(MAKE) replay-pair
	@printf '\n%s\n' '=== 2. Replay that recording and print the historical traceback ==='
	$(MAKE) show-failure
	@printf '\n%s\n' '=== 3. Open the same recording in VS Code ==='
	@printf '%s\n' 'Run: code .'
	@printf '%s\n' 'Then select: Dev Containers: Reopen in Container'

compare:
	@printf '\n%s\n' '=== 1. Prepare and verify the paired historical executions ==='
	$(MAKE) replay-pair
	@printf '\n%s\n' '=== 2. Replay the passing execution with networking disabled ==='
	$(MAKE) show-success
	@printf '\n%s\n' '=== 3. Replay the divergent failing execution with networking disabled ==='
	$(MAKE) show-failure

replay-pair: preflight build
	python3 -m scripts.run_replay_example

replay-example: replay-pair

show-success: preflight
	python3 -m scripts.show_success

show-failure: preflight
	python3 -m scripts.show_failure

presentation: investigate

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
	python3 -m scripts.prepare_vscode --recording failure

vscode-success:
	python3 -m scripts.prepare_vscode --recording success

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --no-color

shell:
	$(COMPOSE) exec agent bash
