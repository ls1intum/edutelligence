# AGENTS.md — logos/docs

Docusaurus site for Logos (user / admin / developer guides, architecture,
deployment, and per-role UI guides). Published by the `Build Logos Documentation`
workflow to https://ls1intum.github.io/edutelligence/logos/.

## Commands

```bash
cd logos/docs
npm ci
npm start          # local preview (usually :3000)
npm run build      # production build — must succeed before merging docs PRs
```

Sidebar and top-nav live in `sidebars.ts` and `docusaurus.config.ts`. Doc ids
are path-based (`roles/app-developer`, `developer/architecture`, …).

## System design diagrams

Structural diagrams for the developer guide live under
`static/img/system-design/` (SVG + `system-design.drawio`). The page is
`developer/system-design.mdx` (Artemis-style: Top-Level, Deployment, Data
Model, Request Flow). Keep the prose and filenames aligned with
[Architecture](developer/architecture.mdx) terminology. Prefer white
backgrounds, one accent colour, and short captions — not dense boxes.

## Role-guide screenshots (committed PNGs)

The pages under `roles/` embed shots from `static/img/roles/`. These **are**
committed to the repo (exception to the usual "screenshots only in the PR
description" rule). Whenever the UI for a documented surface changes in a way
that makes a shot stale — empty, wrong route, error banner, outdated chrome —
refresh the matching PNG in the **same PR**. A follow-up docs-only PR is
allowed only when the UI change already merged without a docs update (debt
cleanup); never defer the PNG refresh out of a UI PR that changes how a
documented page looks.

Capture technique (unlock `.main-content` scroll, wait for non-skeleton
content, force light theme, use `localhost` not `127.0.0.1`) is the
[`ui-screenshots`](../.agents/skills/ui-screenshots/SKILL.md) skill. Do **not**
gist-host role docs shots — overwrite the files under `static/img/roles/`
directly. Desktop viewport only (≈1440×900); no mobile variants for role docs.

### Principles (what to shoot and how to write)

Role guides explain **flows**, not a gallery of near-identical full pages.

1. **One shot per distinct UI state — never per role when the UI is the same.**
   If two roles see the same page (same tabs, same form, same wizard), capture
   it **once** and link other roles to that section. Do **not** keep
   `logos-admin-foo.png` / `app-admin-foo.png` / `app-developer-foo.png` that
   differ only by the sidebar role badge or the API-key dropdown value.
   Existing examples: AI Tools (six wizard steps), Batches (one page), Team
   detail (one tab walkthrough + Logos-Admin-only Providers).

2. **Do shoot every meaningful state of a flow.** Prefer depth over
   duplication. For a documented feature, capture and explain:
   - each **wizard / stepper** step
   - each **tab** on a detail view
   - each important **modal / dialog** (create, edit, confirm, reveal-once
     secrets, …)
   - other distinct panes the reader must understand (empty vs filled only
     when the empty state is part of the product story — seeded happy-path
     shots are the default)

3. **Every committed PNG must appear in the docs.** No orphan files under
   `static/img/roles/`. If you add a shot, name it in the shot matrix below
   **and** embed it next to the prose that explains that state. If you remove
   a shot from the guide, delete the PNG in the same change.

4. **Explain the flow thoroughly.** Prose + screenshots walk the reader
   through the task in order (what this step is for → what to click / enter
   → what happens next). Do not dump a page shot with a one-line caption and
   move on when the UI has multiple steps, tabs, or dialogs.

5. **Name concepts consistently.** Use the same labels the UI shows
   (tab titles, button text, field labels, role names like `Logos Admin` /
   `App Admin` / `App Developer`, entities like **Application Keys**,
   **My Workspace**, **Batches**). File names should mirror those concepts
   (`team-detail-application-keys.png`, `ai-tools-step-connect.png`), not
   invent synonyms (`api-keys` vs `application-keys`, `coding-tools` vs
   `ai-tools`).

When a surface is role-specific (different columns, extra tabs, admin-only
actions), keep a **role-prefixed** list/page shot for that role. When only a
slice differs (e.g. Providers on team detail), document the shared flow once
and add the extra shot only where that role is explained.

### When to refresh

- UI layout / labels / sidebar sections for a documented page changed.
- A review says the shot is empty, wrong page, error page, or role-mismatched.
- After merging large UI work into `main`, before a docs release.
- A new modal, tab, or wizard step is part of a documented flow — add a shot
  and prose for it; do not leave it undescribed.

### Stack

Prefer the throwaway parallel stack so a normal `docker-compose.dev.yaml`
session can keep running:

```bash
# from logos/
docker compose -f docker-compose.screenshots.yaml --project-name logos-doks up -d --build

# UI proxies /api → webservice :19082 (no Traefik in this compose):
cat > /tmp/logos-doks-proxy.conf.json <<'EOF'
{"/api": {"target": "http://127.0.0.1:19082", "secure": false, "changeOrigin": true, "pathRewrite": {"^/api": ""}, "ws": true, "logLevel": "warn"}}
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

Overwrite exactly these files (path relative to `static/img/roles/`). Shared
flows use a **concept** name (no role prefix); role-only list pages keep the
`logos-admin-` / `app-admin-` / `app-developer-` prefix.

| File | Login as | Route / state | Documented in |
|---|---|---|---|
| `logos-admin-statistics.png` | `tobias.wasner` | `/statistics` | `roles/logos-admin.md` |
| `logos-admin-models.png` | `tobias.wasner` | `/models` | `roles/logos-admin.md` |
| `logos-admin-providers.png` | `tobias.wasner` | `/providers` | `roles/logos-admin.md` |
| `logos-admin-policies.png` | `tobias.wasner` | `/policies` | `roles/logos-admin.md` |
| `logos-admin-billing.png` | `tobias.wasner` | `/billing` | `roles/logos-admin.md` |
| `logos-admin-user-management.png` | `tobias.wasner` | `/user-management` | `roles/logos-admin.md` |
| `logos-admin-team-management.png` | `tobias.wasner` | `/team-management` | `roles/logos-admin.md` |
| `logos-admin-agents.png` | `tobias.wasner` | `/agents` | `roles/logos-admin.md` |
| `logos-admin-my-workspace.png` | `tobias.wasner` | `/my-workspace` | `roles/logos-admin.md` |
| `app-admin-models.png` | `alexandra.szuminska` | `/models` | `roles/app-admin.md` |
| `app-admin-user-management.png` | `alexandra.szuminska` | `/user-management` | `roles/app-admin.md` |
| `app-admin-team-management.png` | `alexandra.szuminska` | `/team-management` | `roles/app-admin.md` |
| `team-detail-overview.png` | owner or `logos_admin` | `/teams/<id>` — **Overview** | `roles/app-admin.md#teams` |
| `team-detail-members.png` | same | `/teams/<id>` — **Members** | same |
| `team-detail-application-keys.png` | owner or `logos_admin` | `/teams/<id>` — **Application Keys** | same |
| `team-detail-models.png` | owner or `logos_admin` | `/teams/<id>` — **Models** | same |
| `team-detail-activity.png` | owner or `logos_admin` | `/teams/<id>` — **Activity** | same |
| `team-detail-cloud-usage.png` | owner or `logos_admin` | `/teams/<id>` — **Cloud Usage** | same |
| `team-detail-settings.png` | owner or `logos_admin` | `/teams/<id>` — **Settings** | same |
| `team-detail-providers.png` | `tobias.wasner` (`logos_admin` only) | `/teams/<id>` — **Providers** | `roles/logos-admin.md#teams` |
| `app-admin-my-workspace.png` | `alexandra.szuminska` | `/my-workspace` | `roles/app-admin.md` |
| `batches.png` | any admin role | `/batches` | `roles/app-admin.md#batches` (Logos Admin links) |
| `app-developer-models.png` | `henriette.huhn` | `/models` | `roles/app-developer.md` |
| `app-developer-my-workspace.png` | `henriette.huhn` | `/my-workspace` | `roles/app-developer.md` |
| `ai-tools-step-tool.png` | any role with a key | `/ai-tools` — step **Tool** | `roles/app-developer.md#ai-tools` |
| `ai-tools-step-team.png` | same (needs **>1** API key) | `/ai-tools` — step **Team** | same |
| `ai-tools-step-model.png` | same | `/ai-tools` — step **Model** | same |
| `ai-tools-step-install.png` | same | `/ai-tools` — step **Install** | same |
| `ai-tools-step-connect.png` | same | `/ai-tools` — step **Connect** | same |
| `ai-tools-step-verify.png` | same | `/ai-tools` — step **Verify** | same |

Shared flows (document once, link from other roles):

- **Team detail** — tab walkthrough under `roles/app-admin.md#teams`; Logos
  Admin links there and only adds **Providers**.
- **AI Tools** — step walkthrough under `roles/app-developer.md#ai-tools`;
  App Admin / Logos Admin link there. No per-role `*-ai-tools.png`.
- **Batches** — one shot under `roles/app-admin.md#batches`; Logos Admin
  links there. No per-role `*-batches.png`.

### Acceptance before committing PNGs

- Correct route / state (sidebar highlight, active tab, open modal, wizard
  step) matches the filename and the surrounding prose.
- Real rows / KPIs / charts — **no** empty tables, **no** skeleton shimmer,
  **no** error banners (unless documenting that state on purpose).
- Every PNG in `static/img/roles/` is listed in the matrix **and** embedded
  in a role guide; every embedded shot is explained in the flow, not left as
  an unlabeled figure.
- Concept names in prose, headings, alt text, and filenames match the UI.
- Batches: at least one `in_progress` and one `completed` row.
- My Workspace: rate-limit bars show used/limit (not blank).
- Light theme.
- No near-duplicate per-role shots of the same UI state.

### Extending the seed

Edit `seed/role-screenshots.sql` when a new role page or flow state needs demo
entities. Keep it idempotent (wipe `environment = 'docs-role-screenshots'` /
docs-namespaced demo entities first). Prefer looking up Keycloak-synced
`users.id` by username over hard-coded ids. Update this AGENTS.md shot matrix
**and** the matching role-guide prose in the same change.

Prefer the throwaway screenshots compose DB (`doks-db`). The seed only
deletes docs-namespaced providers/policies and models exclusive to those
providers; it does not overwrite budget/limits on a pre-existing team just
because it is named `Logos`.
