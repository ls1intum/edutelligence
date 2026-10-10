# logos-webservice

Spring Boot service that handles all management REST APIs for the Logos LLM platform. It runs alongside the Python `logos-orchestrator` - Traefik routes frontend traffic to this service at priority 200, overriding the Python routes at priority 100.

## Architecture overview

```
Browser / logos-ui / API clients
      │
  Traefik :8080
      ├── /v1/*, /openai/*, /jobs/*             → logos-webservice gateway (priority 100; scaleable)
      │                                            cloud named-model → Azure/OpenAI directly
      │                                            local / mixed → reverse-proxy to orchestrator
      ├── /api/me, /api/users, /api/teams      → logos-webservice (priority 200, strip /api)
      ├── /api/public/stats?days=…              → logos-webservice (priority 200, strip /api;
      │                                            opted-in teams only; default days=30)
      ├── /api/logosdb/*                        → logos-webservice (priority 200, strip /api)
      ├── /api/admin/*                          → logos-webservice (priority 200, strip /api)
      ├── /api/ws/stats, /api/ws/stats/v2       → logos-webservice (priority 200, strip /api)
      └── /docs/*, /metrics/*, logosnode admin  → logos-orchestrator (Python)
```

Spring sees management paths **without** the `/api` prefix (Traefik strips it). Inference paths (`/v1`, …) keep their public prefix. The database is shared with the Python service — schema is managed by Liquibase.

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

## Public stats (`GET /public/stats`)

Unauthenticated aggregates for the `/stats` page. Rate-limited per source IP, and
cached per window for `logos.public-stats.cache-ttl` (default `PT5M`, `0s` turns
the cache off), so figures can be a few minutes old.

Query parameter `days` (default `30`): `7`, `30`, `90`, `365`, or `all`. Applied to
every request-derived figure (per-team, key type, lane, active students, average).

**Totals stay consistent with what is shown:** only teams with
`teams.show_on_public_stats = true` (set in team settings) appear by name, and
their traffic alone feeds `successful_requests`, the key-type and lane splits,
and the active-student count. Non-selected teams are never named and never
folded into those totals. `teams` is the count of opted-in teams (including
those with no traffic in the window). `students` are distinct active users with
role `app_developer` (admins count as staff) who made at least one successful
request on an opted-in team inside the window.

Every request figure — the totals above and the usage figures below — comes
from one pass over the successful `log_entry` rows of the opted-in teams, ranged
on `timestamp_request`, so they all count the same requests:

| Field | Window | Meaning |
|-------|--------|---------|
| `tokens`, `local_cloud_tokens` | `days` | Tokens of successful requests, total and by lane. |
| `active_persons`, `active_teams` | `days` | People (any role) and teams with a successful request. |
| `usage_per_person`, `usage_per_team` | `days` | Median and 90th percentile of requests, tokens and active days. Per-person values are `null` (`suppressed: true`) below five active people. |
| `categories` | `days` | Requests, tokens and active teams per `teams.public_category` (free text set in team settings; `null` = uncategorized). |
| `models` | `days` | Top models (`all`, `local`, `cloud`) by requests, with tokens; the tail is one `other` row. |
| `regular_activity` | last 4 complete weeks | People and teams active in at least 3 / all 4 weeks. |
| `monthly` | all time | Active teams, people, students, requests, tokens and Logos Agent sessions per UTC month. |
| `agent` | `days` | Logos Agent sessions, distinct starters, successes and pull requests. |

## Adding a new endpoint

1. **Add a controller** in the appropriate domain's `controller/` package — annotate with `@RestController`, inject `AuthContext` via `@RequestAttribute`.
2. **Add a service** in `service/` with the business logic.
3. **Add a Traefik route** in `docker-compose.dev.yaml` if the path prefix isn't already covered (check the `logos-webservice` labels block).
4. **Add a test** — `@SpringBootTest @Import(TestContainersConfig.class)` for integration tests with a real DB; `@WebMvcTest` for controller-layer tests with a mocked service.
5. **Add SQL seed/cleanup** in `src/test/resources/sql/` if the test needs data.
