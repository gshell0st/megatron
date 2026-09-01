.PHONY: all setup build up down restart logs shell clean

# `make` alone: first-time setup (never overwrites existing .env/scope.yaml),
# build the image, start the container.
all: setup build up

setup:
	@[ -f .env ] || cp .env.example .env
	@[ -f scope.yaml ] || cp scope.yaml.example scope.yaml
	@grep -v '^MEGATRON_HOST_HOME=' .env > .env.tmp 2>/dev/null || true
	@echo "MEGATRON_HOST_HOME=$$HOME" >> .env.tmp
	@mv .env.tmp .env
	@echo "scope.yaml e .env prontos (edite-os antes de rodar contra alvos reais, se ainda nao fez)."

build:
	docker compose build

up: setup
	docker compose up -d
	@echo "megatron subindo. Acompanhe com: make logs"

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

shell:
	docker compose exec megatron bash

clean:
	docker compose down -v
