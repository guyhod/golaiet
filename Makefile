PY := ./.venv/bin/python

.PHONY: up stack logs down migrate run scheduler dashboard-dev test superuser shell

up:            ## Postgres only (host dev: make run / make scheduler)
	docker compose up -d db

stack:         ## the whole stack in compose (db + scheduler + web + dashboard on 8003)
	docker compose up -d --build

logs:
	docker compose logs -f scheduler web dashboard

down:
	docker compose down

migrate:
	$(PY) manage.py migrate

run:           ## Django admin + API on 8003 (host dev; the dashboard is make dashboard-dev)
	$(PY) manage.py runserver 127.0.0.1:8003

scheduler:     ## the job loop + Telegram poller (the only APScheduler registrar)
	$(PY) manage.py run_scheduler

dashboard-dev: ## Vite dev server on 5174 with /api proxied to 8003 (host dev)
	cd dashboard && npm install && npm run dev

test:
	$(PY) -m pytest

superuser:
	$(PY) manage.py createsuperuser

shell:
	$(PY) manage.py shell
