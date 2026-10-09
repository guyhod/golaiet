PY := ./.venv/bin/python

.PHONY: up stack logs down migrate run scheduler test superuser shell

up:            ## Postgres only (host dev: make run / make scheduler)
	docker compose up -d db

stack:         ## the whole stack in compose (db + scheduler + web)
	docker compose up -d --build

logs:
	docker compose logs -f scheduler web

down:
	docker compose down

migrate:
	$(PY) manage.py migrate

run:           ## web/admin/API (dev)
	$(PY) manage.py runserver 127.0.0.1:8003

scheduler:     ## the job loop + Telegram poller (the only APScheduler registrar)
	$(PY) manage.py run_scheduler

test:
	$(PY) -m pytest

superuser:
	$(PY) manage.py createsuperuser

shell:
	$(PY) manage.py shell
