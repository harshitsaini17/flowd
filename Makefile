# Short commands for installing, running and developing flowd. `make` lists them.
.DEFAULT_GOAL := help
.PHONY: help install uninstall run start stop restart status logs check test ui ui-test

SERVICES := flowd-llm.service flowd.service

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install: ## Install flowd and start it at login (safe to re-run)
	@scripts/install.sh

uninstall: ## Stop flowd and remove its services (keeps models and config)
	@scripts/uninstall.sh

run: ## Run flowd in this terminal instead of as a service (Ctrl+C to stop)
	uv run flowd

start: ## Start the services
	systemctl --user start $(SERVICES)

stop: ## Stop the services
	systemctl --user stop flowd.service flowd-llm.service

restart: ## Restart the services, e.g. after a git pull
	systemctl --user restart $(SERVICES)

status: ## Show whether flowd is running and what it is doing
	@for s in $(SERVICES); do printf '  %-18s %s\n' "$$s" "$$(systemctl --user is-active $$s)"; done
	@./flowctl status || true

logs: ## Follow the daemon log
	journalctl --user -u flowd -f

check: ## Check idle memory, CPU, and that the microphone is free
	uv run python scripts/idle_check.py --seconds 10

test: ## Run the linters, type checks and tests, as CI does
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy flowd flowctl eval
	uv run pytest -q
	@if command -v cmake >/dev/null 2>&1; then $(MAKE) --no-print-directory ui-test; fi

ui: ## Build the indicator and popup (flowd-ui) into build/ui
	cmake -S ui -B build/ui -DCMAKE_BUILD_TYPE=Release
	cmake --build build/ui -j

ui-test: ui ## Run the flowd-ui unit tests
	ctest --test-dir build/ui --output-on-failure
