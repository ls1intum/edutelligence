# AGENTS.md — logos-webservice

Spring Boot (Java 25, Maven) service: all management REST APIs for the Logos platform — identity (`/me`, `/users`, `/teams`), configuration (models, providers, policies, permissions), admin export/import, operations (stats, billing, request logs), and the stats websockets. Runs alongside `logos-orchestrator`; Traefik routes `/api/*` here at priority 200 (stripping the `/api` prefix — Spring sees paths without it) and lets the orchestrator answer the rest.

**This service owns the Postgres schema** via Liquibase.

## Commands

```bash
mvn spring-boot:run        # run locally (needs the logos-db container up)
mvn test                   # all tests — Testcontainers, Docker must be running
mvn test -Dtest=UserControllerTest   # one class
mvn compile -q             # fast check
```

## Schema changes (Liquibase) — CRITICAL

1. Create `src/main/resources/liquibase/changelog/NNN_description.xml` with the next number after the highest currently included.
2. **Always** add `<include file="liquibase/changelog/NNN_description.xml"/>` to `master.xml` in the same directory — Liquibase only applies changelogs listed there; a file left out is silently never run.
3. Changelogs run automatically on service startup (`spring.liquibase.change-log` in `application.properties`). There is no `init.sql` to keep in sync — `logos/db/` is a plain postgres Dockerfile.
4. After a schema change, update the orchestrator side (`dbutils/dbmanager.py` raw SQL, `dbutils/dbmodules.py` ORM models) to match — see `logos-orchestrator/AGENTS.md`.

## Architecture

- **Auth**: Keycloak JWT (resource server). `auth/JwtAuthInterceptor` maps claims onto the request, `KeycloakUserSyncService` keeps local `users` rows in sync. Special cases: `POST /internal/models_discovered` is gated on the internal secret, not JWT; `/logosdb/get_model_health` likewise (see `auth/SecurityConfig.java`).
- **JPA**: `ddl-auto=validate` — entities never create tables; Liquibase is the only source of schema.
- Each domain package follows `controller/ service/ repository/ entity/ dto/` (see `README.md` for the package map); `admin/` has no entities/repositories of its own, `common/` has no sub-packages.

## Tests

- Testcontainers-based; Docker must be running. No external database needed.
- `src/test/resources/sql/seed-*.sql` insert data before each test, `cleanup-*.sql` remove it after.
- When a method-level `@Sql` adds fixtures **on top of** class-level seeds, use `@SqlMergeMode(SqlMergeMode.MergeMode.MERGE)` on the method — otherwise the method script replaces the class seeds.
