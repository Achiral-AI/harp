.PHONY: help up down logs build smoke patch-warp test fmt watch stats

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start the harp + litellm stack.
	docker compose up -d --build

down: ## Stop and remove the stack.
	docker compose down

logs: ## Tail harp and litellm logs.
	docker compose logs -f --tail=200

build: ## Rebuild the harp image.
	docker compose build harp

smoke: ## Hit harp's /healthz endpoint.
	@curl -fsS "http://127.0.0.1:$${SHIM_PORT:-8787}/healthz" && echo

stats: ## Print one /stats snapshot as JSON.
	@curl -fsS "http://127.0.0.1:$${SHIM_PORT:-8787}/stats" | python3 -m json.tool

watch: ## Live dashboard: local-serve ratio, refreshed every second.
	@./scripts/harp-watch

patch-warp: ## Apply the channel patch to a Warp checkout. Usage: make patch-warp WARP_DIR=/path/to/warp
	@test -n "$(WARP_DIR)" || (echo "Set WARP_DIR=/path/to/warp"; exit 1)
	cd "$(WARP_DIR)" && git apply $(CURDIR)/patches/0001-allow-oss-channel-server-url-override.patch
	@echo "Patch applied. Now run: WARP_SERVER_ROOT_URL=http://127.0.0.1:$${SHIM_PORT:-8787} ./script/run"

test: ## Run harp unit tests.
	python -m pytest -q

fmt: ## Format Python sources.
	python -m ruff format src tests
