.DEFAULT_GOAL := help
PY ?= python

.PHONY: help setup demo test lint typecheck ci report clean smoke record

help:
	@echo "make setup      Install the package with dev extras"
	@echo "make demo       Run both reference agents against the catalogue (no API key needed)"
	@echo "make test       Run the full offline test suite"
	@echo "make lint       ruff check + format check"
	@echo "make typecheck  mypy --strict"
	@echo "make ci         lint + typecheck + test"
	@echo "make report RUN=<run_id>   Regenerate reports from a ledger"
	@echo "make clean      Remove run artifacts and caches"
	@echo "make smoke      Check the LLM provider is reachable (needs GROQ_API_KEY)"
	@echo "make record     Record cassettes from a live run (needs GROQ_API_KEY)"

setup:
	$(PY) -m pip install -e ".[dev]"

demo:
	$(PY) -m gauntlet demo

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

typecheck:
	$(PY) -m mypy

ci: lint typecheck test

report:
	$(PY) -m gauntlet report $(RUN)

smoke:
	$(PY) scripts/smoke_groq.py

# Records the exchanges `make demo` replays. Run once, by hand, with a key.
# Never during a scored run: a cassette should hold a clean recording, not
# whatever happened to come back that time.
record:
	GAUNTLET_RECORD=1 GAUNTLET_MODE=live $(PY) -m gauntlet compare --agents naive,hardened

clean:
	$(PY) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['runs','.pytest_cache','.mypy_cache','.ruff_cache','htmlcov']]"
	$(PY) -c "import pathlib,shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
