# AGENTS.md — logos/docs

Docusaurus site for Logos (user / admin / developer guides, architecture,
deployment, and per-role UI guides). Published by the `Build Logos Documentation`
workflow to <https://ls1intum.github.io/edutelligence/logos/>.

## Commands

```bash
cd logos/docs
npm ci
npm start          # local preview (usually :3000)
npm run build      # production build — must succeed before merging docs PRs
```

Sidebar and top-nav live in `sidebars.ts` and `docusaurus.config.ts`. Doc ids
are path-based (`roles/app-developer`, `developer/architecture`, …).

## Role-guide screenshots (committed PNGs)

The pages under `roles/` embed full-page shots from `static/img/roles/`. These
**are** committed to the repo (exception to the usual "screenshots only in the
PR description" rule). Whenever the UI for a documented page changes in a way
that makes a shot stale — empty, wrong route, error banner, outdated chrome —
refresh the matching PNG in the same PR that changes the docs (or a follow-up
docs PR).

Capture technique (unlock `.main-content` scroll, wait for non-skeleton
content, force light theme, use `localhost` not `127.0.0.1`) is the
[`ui-screenshots`](../.agents/skills/ui-screenshots/SKILL.md) skill. Do **not**
gist-host role docs shots — overwrite the files under `static/img/roles/`
directly. Desktop viewport only (≈1440×900); no mobile variants for role docs.

### When to refresh

- UI layout / labels / sidebar sections for a documented page changed.
- A review says the shot is empty, wrong page, error page, or role-mismatched.
- After merging large UI work into `main`, before a docs release.

### Stack

Prefer the throwaway parallel stack so a normal `docker-compose.dev.yaml`
session can keep running:

```bash
# from logos/
docker compose -f docker-compose.screenshots.yaml --project-name logos-doks up -d --build

# UI proxies /api → webservice :19082 (no Traefik in this compose):
cat > /tmp/logos-doks-proxy.conf.json <<'EOF'
{"/api": {"target": "http://127.0.0.1:19082", "secure": false, "changeOrigin": true, "logLevel": "warn"}}
EOF
cd logos-ui && ng serve --port 4300 --proxy-config /tmp/logos-doks-proxy.conf.json
```

Open **`http://localhost:4300/`** (CORS allowlist includes that origin). Keycloak
is on `:18085`, DB on `127.0.0.1:15432`. Tear down with
`docker compose -f docker-compose.screenshots.yaml --project-name logos-doks down -v`
when finished.

The ordinary `docker-compose.dev.yaml` + `ng serve` on `:4200` also works; point
`psql` at that stack's DB instead of `15432`.

### Prime with example data (required)

A fresh stack has **no teams, models, usage, batches, or agent sessions**.
Empty / error / skeleton shots are not acceptable. Always prime before
capturing.

1. **Log in once** as each role so Keycloak sync creates the `users` rows
   (password for every seeded account is `password` — see `../README.md`):

   | Username | Logos role | Use for |
   |---|---|---|
   | `tobias.wasner` | `logos_admin` | all `logos-admin-*.png` |
   | `alexandra.szuminska` | `app_admin` | all `app-admin-*.png` |
   | `henriette.huhn` | `app_developer` | all `app-developer-*.png` |

2. **Apply the defined seed** (idempotent; tags demo rows with
   `environment = 'docs-role-screenshots'` and wipes the previous run first):

   ```bash
   # screenshots compose DB:
   docker exec -i doks-db psql -U postgres -d logosdb < logos/docs/seed/role-screenshots.sql

   # or against the normal dev DB container name:
   # docker exec -i <logos-db-container> psql -U postgres -d logosdb < logos/docs/seed/role-screenshots.sql
   ```

   The seed creates: team **Logos** with the three users as members; developer
   + application keys with rate-limit settings; cloud + local-looking
   providers and three models (capabilities, aliases, prices); policies;
   priced `log_entry` rows (billing + statistics + My Workspace usage bars);
   one `in_progress` and one `completed` batch; agent workspaces/sessions;
   and team budget / default rate limits for the team-detail overview.

3. If the seed aborts with `required Keycloak users missing`, finish step 1
   and re-run. Do **not** invent alternate usernames — the role guides and
   shots assume these three.

4. Soft-refresh the UI (or re-login) after seeding so caches pick up the data.

### Shot matrix

Overwrite exactly these files (path relative to `static/img/roles/`):

| File | Login as | Route |
|---|---|---|
| `logos-admin-statistics.png` | `tobias.wasner` | `/statistics` |
| `logos-admin-models.png` | `tobias.wasner` | `/models` |
| `logos-admin-providers.png` | `tobias.wasner` | `/providers` |
| `logos-admin-policies.png` | `tobias.wasner` | `/policies` |
| `logos-admin-billing.png` | `tobias.wasner` | `/billing` |
| `logos-admin-user-management.png` | `tobias.wasner` | `/user-management` |
| `logos-admin-team-management.png` | `tobias.wasner` | `/team-management` |
| `logos-admin-agents.png` | `tobias.wasner` | `/agents` |
| `logos-admin-my-workspace.png` | `tobias.wasner` | `/my-workspace` |
| `logos-admin-batches.png` | `tobias.wasner` | `/batches` |
| `app-admin-models.png` | `alexandra.szuminska` | `/models` |
| `app-admin-user-management.png` | `alexandra.szuminska` | `/user-management` |
| `app-admin-team-management.png` | `alexandra.szuminska` | `/team-management` |
| `team-detail-overview.png` | owner or `logos_admin` | `/teams/<id>` — **Overview** |
| `team-detail-members.png` | same | `/teams/<id>` — **Members** |
| `team-detail-application-keys.png` | owner or `logos_admin` | `/teams/<id>` — **Application Keys** |
| `team-detail-models.png` | owner or `logos_admin` | `/teams/<id>` — **Models** |
| `team-detail-activity.png` | owner or `logos_admin` | `/teams/<id>` — **Activity** |
| `team-detail-cloud-usage.png` | owner or `logos_admin` | `/teams/<id>` — **Cloud Usage** |
| `team-detail-settings.png` | owner or `logos_admin` | `/teams/<id>` — **Settings** |
| `team-detail-providers.png` | `tobias.wasner` (`logos_admin` only) | `/teams/<id>` — **Providers** |

Team detail is documented once under `roles/app-admin.md#teams` (tab walkthrough);
Logos Admin links there and only adds the Providers shot. Do not keep
separate `*-team-management-detail.png` per role.
| `app-admin-my-workspace.png` | `alexandra.szuminska` | `/my-workspace` |
| `app-admin-batches.png` | `alexandra.szuminska` | `/batches` |
| `app-developer-models.png` | `henriette.huhn` | `/models` |
| `app-developer-my-workspace.png` | `henriette.huhn` | `/my-workspace` |
| `ai-tools-step-tool.png` | any role with a key | `/ai-tools` — step **Tool** |
| `ai-tools-step-team.png` | same (needs **>1** API key) | `/ai-tools` — step **Team** |
| `ai-tools-step-model.png` | same | `/ai-tools` — step **Model** |
| `ai-tools-step-install.png` | same | `/ai-tools` — step **Install** |
| `ai-tools-step-connect.png` | same | `/ai-tools` — step **Connect** |
| `ai-tools-step-verify.png` | same | `/ai-tools` — step **Verify** |

AI Tools is **not** documented per role — the wizard is identical for every
role. Keep one step walkthrough under `roles/app-developer.md#ai-tools` and
link App Admin / Logos Admin there. Capture the six `ai-tools-step-*.png`
files (give the user a second API key so **Team** is not skipped). Do not
reintroduce `*-ai-tools.png` per role.


### Acceptance before committing PNGs

- Correct route (sidebar highlight matches the page).
- Real rows / KPIs / charts — **no** empty tables, **no** skeleton shimmer,
  **no** error banners.
- Batches: at least one `in_progress` and one `completed` row.
- My Workspace: rate-limit bars show used/limit (not blank).
- Team detail: Overview with Members / Application Keys / Models / … tabs.
- Light theme.

### Extending the seed

Edit `seed/role-screenshots.sql` when a new role page needs demo entities.
Keep it idempotent (wipe `environment = 'docs-role-screenshots'` / known demo
names first). Prefer looking up Keycloak-synced `users.id` by username over
hard-coded ids. Update this AGENTS.md shot matrix in the same change.
