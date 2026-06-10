# logos-webservice

Spring Boot service that handles all management REST APIs for the Logos LLM platform. It runs alongside the Python `logos-orchestrator` - Traefik routes frontend traffic to this service at priority 200, overriding the Python routes at priority 100.

## Architecture overview

```
Browser / logos-ui
      │
  Traefik :8080
      ├── /api/me, /api/users, /api/teams      → logos-webservice (priority 200, strip /api)
      ├── /api/logosdb/*                        → logos-webservice (priority 200, strip /api)
      ├── /api/admin/*                          → logos-webservice (priority 200, strip /api)
      ├── /api/ws/stats, /api/ws/stats/v2       → logos-webservice (priority 200, strip /api)
      ├── /v1/*, /openai/*, /jobs/*             → logos-orchestrator (Python, priority 100)
      └── /api/*, /docs/*, /metrics/*           → logos-orchestrator (Python, priority 100)
```

Spring sees paths **without** the `/api` prefix (Traefik strips it). The database is shared with the Python service — schema is managed by Liquibase.

## Prerequisites

| Tool | Version |
|------|---------|
| Java | 25 |
| Maven | 3.9+ |
| Docker + Docker Compose | any recent |
| PostgreSQL | 17 (provided by Docker) |

## Running in Docker (recommended)

From the repo root:

```bash
docker compose -f logos/docker-compose.dev.yaml up --build
```

The service starts on port `18082` (direct) and is reachable through Traefik on port `18081` at `/api/*`.

## Running locally (outside Docker)

Start the database first:

```bash
docker compose -f logos/docker-compose.dev.yaml up logos-db
```

Then run the Spring app:

```bash
cd logos-webservice
mvn spring-boot:run
```

The app starts on `http://localhost:8081`. Set environment variables to override the defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | `localhost` | PostgreSQL hostname |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `logosdb` | Database name |
| `DB_USER` | `postgres` | DB username |
| `DB_PASSWORD` | `root` | DB password |

## Running tests

Tests use Testcontainers — Docker must be running. No external database needed.

```bash
# Run all tests
mvn test -pl logos-webservice

# Run a single test class
mvn test -pl logos-webservice -Dtest=UserControllerTest

# Compile only (fast check)
mvn compile -pl logos-webservice -q
```

Test resources live in `src/test/resources/sql/`: `seed-*.sql` files insert test data before each test, `cleanup-*.sql` files remove it after.

## Package structure

```
src/main/java/.../logoswebservice/
├── auth/
│   ├── AuthContext.java          — record(keyValue, apiKeyId, keyName, keyType, teamId, userId, role)
│   ├── AuthInterceptor.java      — reads X-API-Key header, populates AuthContext per request
│   └── WebConfig.java            — registers AuthInterceptor
├── common/
│   ├── GlobalExceptionHandler.java — @RestControllerAdvice for common error responses
│   └── JacksonConfig.java          — Jackson serialization settings
├── identity/                     — /me, /users/*, /teams/*, /admin/api-keys/*
├── configuration/                — /logosdb/models, providers, policies; /admin/permissions
├── admin/                        — /logosdb/export, /logosdb/import
├── operations/                   — /logosdb/stats, billing, request logs, VRAM
└── websocket/                    — /ws/stats (v1) and /ws/stats/v2
```

Each domain follows the same structure:

```
<domain>/
├── controller/   — @RestController, injects AuthContext and service
├── service/      — business logic, uses JPA repositories + JdbcTemplate
├── repository/   — Spring Data JPA interfaces
├── entity/       — @Entity classes (JPA, ddl-auto=validate — never auto-creates tables)
└── dto/          — request/response POJOs
```

Note: not every domain has all layers — `admin/` only has a controller and service (no entities or repositories of its own), and `common/` has no sub-packages.

## Authentication

Every request must include a valid `X-API-Key` header. `AuthInterceptor` looks up the key in the database and stores an `AuthContext` record as a request attribute. Controllers access it via:

```java
@RequestAttribute("authContext") AuthContext auth
```

Roles (lowest to highest): `app_developer` → `app_admin` → `logos_admin`.

WebSocket connections authenticate via the same `X-API-Key` query parameter or header, handled by `WebSocketAuthInterceptor`.

## Schema changes (Liquibase)

**Never edit `db/init.sql` or add files to `db/migrations/`.** Those are the old Python-era migration system.

To change the schema:

1. Create a new XML changeset file:
   `src/main/resources/liquibase/changelog/001_your_change.xml`

2. Register it in `master.xml`:
   ```xml
   <include file="liquibase/changelog/001_your_change.xml"/>
   ```

3. Liquibase runs on startup and applies unapplied changesets automatically.

Example changeset:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog
        http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-latest.xsd">

    <changeSet id="001" author="logos">
        <addColumn tableName="users">
            <column name="display_name" type="VARCHAR(255)"/>
        </addColumn>
    </changeSet>
</databaseChangeLog>
```

## Adding a new endpoint

1. **Add a controller** in the appropriate domain's `controller/` package — annotate with `@RestController`, inject `AuthContext` via `@RequestAttribute`.
2. **Add a service** in `service/` with the business logic.
3. **Add a Traefik route** in `docker-compose.dev.yaml` if the path prefix isn't already covered (check the `logos-webservice` labels block).
4. **Add a test** — `@SpringBootTest @Import(TestContainersConfig.class)` for integration tests with a real DB; `@WebMvcTest` for controller-layer tests with a mocked service.
5. **Add SQL seed/cleanup** in `src/test/resources/sql/` if the test needs data.
