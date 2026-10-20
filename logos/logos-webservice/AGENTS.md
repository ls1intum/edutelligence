# AGENTS.md — logos-webservice

Spring Boot (Java 25, Maven) service: management REST APIs for the Logos platform — identity (`/me`, `/users`, `/teams`), configuration (models, providers, policies, permissions), admin export/import, operations (stats, billing, request logs), and the stats websockets — **and** the public inference gateway for `/v1/**`, `/openai/**`, `/jobs/**` (`gateway/`). Traefik routes those prefixes here at priority 100 (multi-instance via Compose scale); `/api/*` stays at priority 200 with the `/api` prefix stripped. Cloud named-model traffic is answered in-process; local/logosnode and mixed paths are reverse-proxied to `logos-orchestrator`.

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

- **Auth**: Keycloak JWT (resource server) for management APIs. `auth/JwtAuthInterceptor` maps claims onto the request, `KeycloakUserSyncService` keeps local `users` rows in sync. Special cases: `POST /internal/models_discovered` is gated on the internal secret, not JWT; `/logosdb/get_model_health` likewise; `/v1/**`, `/openai/**`, `/jobs/**` use Logos API keys in the inference gateway (see `auth/SecurityConfig.java` and `gateway/`).
- **Inference gateway** (`gateway/`): one-query auth+permissions on the named-model cloud path; approximate monthly budget with a short TTL cache that an admission never waits on once a key has a snapshot: an expired snapshot answers while one refresh runs in the background (see `GatewayBudgetService`); streaming cloud forward or orchestrator reverse-proxy. Remaining process state is named on `InferenceGatewayController`. **The admission path must stay lock-free and O(the key's recent rows)** — no `FOR UPDATE`, no cache drop, no table-wide sweep per request; anything that scans `log_entry` beyond one key's window belongs in a scheduled sweep (`reconcileStale`, `finalizeUnsettled`), each kept cheap by its partial index (`idx_log_entry_gateway_in_flight`, changelog 043; `idx_log_entry_gateway_unfinalized`, changelog 060). Cloud RPM and TPM are enforced in Redis (`GatewayCloudRateLimiter`, shared sliding window across replicas) before budget reservation. A direct-cloud request is admitted against a flat reservation and then billed from the token usage its response reports (`GatewayUsageCapture` reads it off the stream, `GatewayCloudAccounting` stores it), so pricing runs through `logos_price_usage` exactly as on the orchestrator path, and the price is stored on the row (`cost_finalized = TRUE`) at settle time — a row left unpriced is re-priced by `log_entry_cost` on every budget refresh, which grows with the key's month of traffic. The refresh sums priced rows straight from `log_entry` and sends only unpriced rows through the view: summing everything through the view makes the planner cost every row at the pricing function's estimate and JIT-compile the query. The reservation stands only when the response reports no usage, or when that usage prices to nothing (no price rows for the deployment). The row is dated from the request's arrival at the controller (`timestamp_request`), not from the insert after admission, so the time spent in authentication, rate limiting and the budget check shows up as queue time (`timestamp_forwarding` − `timestamp_request`); the forwarder records the provider window (`timestamp_provider_call`, `time_at_first_token`, `timestamp_provider_response`) on settle. The row also stores the reasoning effort the body carries (`reasoning_effort`, see `GatewayReasoningEffort`); the body is forwarded unchanged, so that is the effort the provider is sent. The row is written at the key's own `log` level, so a `FULL` key stores its request and response payloads; a streamed response has no single body to store.
- **JPA**: `ddl-auto=validate` — entities never create tables; Liquibase is the only source of schema.
- Each domain package follows `controller/ service/ repository/ entity/ dto/` (see `README.md` for the package map); `admin/` has no entities/repositories of its own, `common/` has no sub-packages; `gateway/` is the inference front door.

## Tests

- Testcontainers-based; Docker must be running. No external database needed.
- `src/test/resources/sql/seed-*.sql` insert data before each test, `cleanup-*.sql` remove it after.
- When a method-level `@Sql` adds fixtures **on top of** class-level seeds, use `@SqlMergeMode(SqlMergeMode.MergeMode.MERGE)` on the method — otherwise the method script replaces the class seeds.
