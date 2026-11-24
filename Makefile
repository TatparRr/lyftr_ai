.PHONY: up down test

PYTHON ?= python3

up:
	docker compose up --build

down:
	docker compose down

test:
	cd backend && $(PYTHON) -m pytest -q
