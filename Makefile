.PHONY: test test-cov lint lint-fix format format-check typecheck deadcode check all
.SILENT:

# Fast test run: pass/fail summary only, no coverage report noise.
test:
	uv run pytest -q --no-cov

# Full test run with coverage report (per-file missing lines).
test-cov:
	uv run pytest -q

# Ruff lint: one line per violation instead of full context blocks.
lint:
	uv run ruff check . --output-format=concise

lint-fix:
	uv run ruff check . --fix --output-format=concise

# Ruff format: apply / verify formatting.
format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

# Dead-code scan; silent on success, lists findings otherwise.
deadcode:
	uv run vulture

# Run every check. Order: cheapest/fastest first so failures surface early.
check: format-check lint typecheck deadcode test

all: check
