.PHONY: bootstrap doctor test lint format check

bootstrap:
	./scripts/bootstrap_mac.sh

doctor:
	uv run amt doctor

test:
	uv run python -m unittest discover -s tests -v

lint:
	uv run python -m compileall -q src tests
	@if uv run ruff --version >/dev/null 2>&1; then uv run ruff check src tests; else echo "ruff not installed; compileall completed"; fi

format:
	@if uv run ruff --version >/dev/null 2>&1; then uv run ruff format src tests; else echo "ruff not installed"; fi

check: doctor test lint
