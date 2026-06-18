# ReelMagic developer commands.
.PHONY: help setup music backend worker frontend test clean cleanup compose-up compose-down

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help:
	@echo "ReelMagic — make targets:"
	@echo "  setup        Create venv, install backend deps, build music + beat maps"
	@echo "  music        (Re)generate bundled tracks + beat maps"
	@echo "  backend      Run the API (uvicorn) on :8000"
	@echo "  worker       Run an RQ worker (needs Redis)"
	@echo "  frontend     Run the Next.js dev server on :3000"
	@echo "  test         Run the backend test suite"
	@echo "  cleanup      Purge media for jobs older than the TTL (48h)"
	@echo "  compose-up   docker compose up --build"
	@echo "  clean        Remove venv, local db, storage, generated media"

setup:
	uv venv --python 3.11 $(VENV) 2>/dev/null || python3 -m venv $(VENV)
	$(PIP) install -r backend/requirements.txt
	cd backend && ../$(PY) scripts/generate_music.py && ../$(PY) scripts/build_beatmaps.py
	@echo "\nSetup done. Copy backend/.env.example -> backend/.env, then `make backend`."

music:
	cd backend && ../$(PY) scripts/generate_music.py && ../$(PY) scripts/build_beatmaps.py

backend:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

worker:
	cd backend && ../$(PY) worker.py

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../$(PY) -m pytest -q

cleanup:
	cd backend && ../$(PY) scripts/cleanup.py

compose-up:
	docker compose up --build

compose-down:
	docker compose down

clean:
	rm -rf $(VENV) backend/data backend/storage backend/sample_trip backend/assets/music/*.wav
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
