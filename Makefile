.PHONY: help install dev test test-cov lint format typecheck precommit build clean all

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Install package
	uv pip install -e .

dev: ## Install package with dev dependencies
	uv pip install -e ".[dev]"

test: ## Run pytest
	uv run pytest tests/

test-cov: ## Run pytest with coverage
	uv run pytest tests/ --cov=src/claude_wiki --cov-report=term-missing

lint: ## Run ruff lint
	uvx ruff check .

format: ## Run ruff format and mdformat
	uvx ruff format .
	uvx --with mdformat-frontmatter --with mdformat-gfm mdformat docs/ .claude/skills/claude-wiki/SKILL.md README.md src/claude_wiki/AGENTS.md

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
