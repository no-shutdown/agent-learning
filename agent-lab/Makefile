PYTHON ?= /opt/homebrew/bin/python3.13
.PHONY: setup run check test typecheck
setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.txt
run:
	set -a; if [ -f .env ]; then . ./.env; fi; set +a; .venv/bin/python src/main.py
check: typecheck
	.venv/bin/python -m compileall -q src evals tests

test:
	PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v

typecheck:
	.venv/bin/python -m mypy
