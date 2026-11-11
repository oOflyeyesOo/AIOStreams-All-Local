SHELL := /bin/sh
COMPOSE := docker compose --env-file .env.example
IMAGE_PREFIX ?= aio-local
IMAGE_TAG ?= release-test
PROFILES := core scrapers proxies web tunnel all

.PHONY: validate test e2e integrations build backup restore

validate:
	python3 scripts/generate_manager_compose.py --check
	$(COMPOSE) -f compose.manager.yml config --quiet
	$(COMPOSE) config --quiet
	$(COMPOSE) -f docker-compose.aio.yml config --quiet
	$(COMPOSE) -f compose.test.yml config --quiet
	@for profile in $(PROFILES); do \
		$(COMPOSE) --profile "$$profile" config --quiet || exit 1; \
	done
	python3 -m tests.check_inventory

test:
	$(COMPOSE) -p aio-tests -f compose.test.yml run --rm tests

e2e:
	docker exec aio-portal python3 /app/tests/check_all_services_e2e.py

integrations:
	python3 -m tests.check_integrations

build:
	docker build -t aiostreams-aio:latest -f docker/all-in-one/Dockerfile .

backup:
	python3 tools/backup.py --backup

restore:
	@test -n "$(ARCHIVE)" || (echo "Usage: make restore ARCHIVE=/path/to/aio-backup.tar.gz" >&2; exit 2)
	python3 tools/backup.py --restore "$(ARCHIVE)"


.PHONY: package
package:
	@for target in portal controller aiostreams stremio-web bootstrap postgres-init search-broker; do \
		docker build -f docker/packaged/Dockerfile --target "$$target" -t "$(IMAGE_PREFIX)-$$target:$(IMAGE_TAG)" . || exit 1; \
	done
	docker build -f docker/anime-kitsu/Dockerfile -t "$(IMAGE_PREFIX)-kitsu:$(IMAGE_TAG)" .
