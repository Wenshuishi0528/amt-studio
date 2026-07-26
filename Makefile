.PHONY: bootstrap doctor test lint format mac-check mac-app check

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

mac-check:
	@if [ "$$(uname -s)" = "Darwin" ] && command -v swift >/dev/null 2>&1; then \
		swift test --package-path apps/AMTStudioMac; \
	else \
		echo "AMTStudioMac tests skipped: macOS Swift toolchain required"; \
	fi

mac-app:
	./apps/AMTStudioMac/scripts/build_app.sh

check: doctor test lint mac-check
