.PHONY: help install dev test test-cov lint format typecheck precommit build clean all pypi-start pypi-stop pypi-status pypi-logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install package
	uv pip install -e .

dev: ## Install package with dev dependencies
	uv sync

install-precommit: ## Install pre-commit git hooks
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

test: ## Run pytest
	uv run pytest tests/

test-cov: ## Run pytest with coverage
	uv run pytest tests/ --cov=src/claude_wiki --cov-report=term-missing

lint: ## Run ruff lint
	uvx ruff check .

format: ## Run ruff format and mdformat
	uvx ruff format .
	uvx --with mdformat-frontmatter --with mdformat-gfm mdformat \
	  .claude/skills/ docs/ README.md CHANGELOG.md src/claude_wiki/AGENTS.md

typecheck: ## Run mypy
	uv run mypy src/

precommit: ## Run all pre-commit hooks
	uv run pre-commit run --all-files

build: ## Build wheel
	uv build

clean: ## Remove build artifacts
	rm -rf dist/ build/ src/*.egg-info/ .mypy_cache/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +

all: format lint typecheck test precommit ## Run full CI gate locally

# Local PyPI registry for testing package publishing
PYPI_DIR = $(HOME)/.local/share/local-pypi
PYPI_PID = $(PYPI_DIR)/pypiserver.pid
PYPI_PORT = 8080

pypi-start: ## Start local PyPI registry on localhost:8080
	@if [ -f $(PYPI_PID) ] && kill -0 $$(cat $(PYPI_PID)) 2>/dev/null; then \
		echo "pypiserver already running (PID: $$(cat $(PYPI_PID)))"; \
	else \
		mkdir -p $(PYPI_DIR)/packages; \
		uv run pypi-server run -p $(PYPI_PORT) -i 127.0.0.1 -a . -P . --disable-fallback $(PYPI_DIR)/packages > $(PYPI_DIR)/pypiserver.log 2>&1 & \
		echo $$! > $(PYPI_PID); \
		echo "pypiserver started on http://localhost:$(PYPI_PORT) (PID: $$(cat $(PYPI_PID)))"; \
	fi

pypi-stop: ## Stop local PyPI registry
	@if [ -f $(PYPI_PID) ]; then \
		PID=$$(cat $(PYPI_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "pypiserver stopped (PID: $$PID)"; \
		else \
			echo "pypiserver not running (stale PID file removed)"; \
		fi; \
		rm -f $(PYPI_PID); \
	else \
		echo "pypiserver not running"; \
	fi

pypi-status: ## Check local PyPI registry status
	@if [ -f $(PYPI_PID) ] && kill -0 $$(cat $(PYPI_PID)) 2>/dev/null; then \
		echo "pypiserver running (PID: $$(cat $(PYPI_PID)))"; \
	else \
		echo "pypiserver not running"; \
	fi

pypi-logs: ## Tail local PyPI registry logs
	@tail -f $(PYPI_DIR)/pypiserver.log
