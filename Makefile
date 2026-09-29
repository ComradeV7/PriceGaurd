.PHONY: install lint test run backtest export

install:
	uv sync --dev

lint:
	uv run ruff check .

test:
	uv run pytest

run:
	uv run python -m priceguard.cli --help

backtest:
	uv run python -m priceguard.cli backtest

export:
	uv run python -m priceguard.cli export
