PYTHON ?= /opt/homebrew/bin/python3.13
.PHONY: setup run check
setup:
	$(PYTHON) -m venv .venv
run:
	set -a; if [ -f .env ]; then . ./.env; fi; set +a; .venv/bin/python src/main.py
check:
	.venv/bin/python -m compileall -q src evals
