PROJECT := ebtto
PYTHON ?= python3

.PHONY: install test lint clean build sdist wheel

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q --no-header -p no:cacheprovider

unit:
	$(PYTHON) -m pytest tests/unit -q

integration:
	$(PYTHON) -m pytest tests/integration -q

contract:
	$(PYTHON) -m pytest tests/contract -q

security:
	$(PYTHON) -m pytest tests/security -q

regression:
	$(PYTHON) -m pytest tests/regression -q

benchmark:
	$(PYTHON) -m pytest tests/benchmark -v

lint:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format --check .

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .coverage
	rm -rf src/hermes_ebtto.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	$(PYTHON) -m build --sdist --wheel --no-isolation

sdist:
	$(PYTHON) -m build --sdist --no-isolation

wheel:
	$(PYTHON) -m build --wheel --no-isolation

doctor:
	hermes plugins validate
	codegraph status .
