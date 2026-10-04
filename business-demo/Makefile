PYTHON ?= /opt/homebrew/bin/python3.13
.PHONY: setup run test check seed reset format
setup:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt
	.venv/bin/python manage.py migrate
run:
	set -a; if [ -f .env ]; then . ./.env; fi; set +a; .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload --insecure
test:
	.venv/bin/python manage.py test tests
check:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/python manage.py check
seed:
	.venv/bin/python manage.py seed_demo
reset:
	.venv/bin/python manage.py seed_demo --reset --yes
format:
	.venv/bin/ruff format .

# Explicit opt-in: bind only the supplied local network address.
.PHONY: run-lan
run-lan:
	@test -n "$(DEMO_LAN_IP)" || (echo '请指定 DEMO_LAN_IP，例如 make run-lan DEMO_LAN_IP=192.168.1.10'; exit 1)
	set -a; if [ -f .env ]; then . ./.env; fi; set +a; DEMO_LAN_IP="$(DEMO_LAN_IP)" .venv/bin/python manage.py runserver "$(DEMO_LAN_IP):8000" --noreload --insecure
