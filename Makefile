.PHONY: install dev test test-unit test-integration lint format validate-scaffolds

install:
	uv pip install -e ".[dev,mantic]"

dev:
	uv run python3 -m cip.core.server.main

test:
	uv run python3 -m pytest tests/ -v

test-unit:
	uv run python3 -m pytest tests/unit/ -v

test-integration:
	uv run python3 -m pytest tests/integration/ -v

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

validate-scaffolds:
	uv run python3 -c "from cip.core.scaffold.loader import load_scaffold_directory; from cip.core.scaffold.registry import ScaffoldRegistry; r = ScaffoldRegistry(); c = load_scaffold_directory('src/cip/domains/health/scaffolds', r); assert c > 0, 'No scaffolds loaded'; ids = [s.id for s in r.list_all()]; print(f'Validated {c} scaffolds: {ids}')"
