---
name: ui-screenshots
description: Capture full-page desktop and mobile screenshots of the Logos Angular web application and host them so they render in a pull request or in the documentation. Use whenever a change touches logos-ui/, when a PR needs UI screenshots, or when adding UI imagery to docs — covers localhost-vs-127.0.0.1 CORS, unlocking shell scroll containers, waiting for real data (not skeletons), and the gist hosting gotcha that otherwise serves images as text. For committed role-guide PNGs under docs/static/img/roles/, also read logos/docs/AGENTS.md (seed + shot matrix).
compatibility: Requires the Logos dev stack (Docker Compose), the GitHub CLI (`gh`) authenticated, and a browser automation tool such as Playwright.
---

# Gathering UI screenshots (for PRs and documentation)

Reviewers must be able to see the result without running the stack; a UI PR without screenshots is not reviewable.

## Requirements

- At least one **desktop** screenshot of the changed view.
- At least one **mobile** screenshot (375px viewport) of the same view — the shared data tables drop their header below 768px and fall back to per-cell `data-label`s, so a mobile shot is the only way to see how a table actually renders there.
- **Every screenshot must show the FULL page** — page header, tab bar, and the entire scrollable content. A shot that starts mid-view or cuts off the last table row is not acceptable.
- Screenshots go into the PR description only — **never commit them to the repository**, except the role-guide PNGs under `docs/static/img/roles/` (see `docs/AGENTS.md`).

## 1. Run the stack and open the UI on `localhost` (not `127.0.0.1`)

```bash
docker compose -f docker-compose.dev.yaml up --build   # from logos/
cd logos-ui && ng serve                                 # UI on http://localhost:4200/
```

**Use `http://localhost:4200/` for every browser URL.** Do **not** use `http://127.0.0.1:4200/`.

Dev CORS (`LOGOS_CORS_ALLOWED_ORIGINS` in `docker-compose.dev.yaml`) allowlists `http://localhost:4200`. Browsers send an `Origin` header on POSTs and WebSocket upgrades; with Origin `http://127.0.0.1:4200` the webservice answers **`403 Invalid CORS request`**. Symptoms that look like a “broken / half-loaded UI”:

- KPI / chart / recent-requests panels stuck on **skeletons** forever
- console: `Failed to load resource: 403` on `/api/logosdb/...`
- WebSocket to `/api/ws/stats/v2` fails handshake with **403**
- curl to the same endpoints **without** an Origin header still returns 200 — that does **not** mean the UI is fine

If you already started `ng serve --host 127.0.0.1`, restart it on `localhost` (default) and recapture.

Log in with a seeded Keycloak user (all passwords `password`), e.g. `tobias.wasner` (logos admin). Flow: app login page → **Sign in with TUM** → Keycloak username/password. See `README.md` for the full user table.

## 2. Capture a true full-page screenshot

### Wait for a settled page (not skeletons)

Do **not** use Playwright `waitUntil: 'networkidle'` — stats WebSockets reconnect and never go idle.

Before shooting:

1. Force light theme so headless Chrome’s `prefers-color-scheme: dark` does not flip tokens mid-paint:

   ```js
   await context.addInitScript(() => localStorage.setItem('logos-theme', 'light'));
   // and/or: await context.newContext({ colorScheme: 'light' })
   ```

2. `await page.evaluate(() => document.fonts.ready)`.

3. Wait until real content replaced skeletons, e.g. for Statistics:

   ```js
   await page.waitForFunction(() => {
     const strip = document.querySelector('.stats-kpi-strip');
     return !!strip
       && !strip.querySelector('app-stats-skeleton')
       && !!strip.querySelector('app-stats-kpi-card');
   }, { timeout: 45_000 });
   ```

   If that times out, check Origin/`localhost` and CORS first — do not ship skeleton-only shots.

### Unlock scroll containers

The Logos UI scrolls inside `.main-content` (shell), not the document — a plain `fullPage` screenshot only captures the first viewport. Unlock, then `fullPage: true`:

- set `height: auto`, `max-height: none`, and `overflow` / `overflow-y: visible` (all `!important`) on `<html>`, `<body>`, `.shell-layout`, `.main-content`, and ancestors of the page root (e.g. `.stats-page`) up to `<html>`
- also unlock every element whose computed `overflow-y` is `auto` or `scroll`

**Do not** blanket-unlock every `overflow: hidden` node on the page (cards, chips, text ellipsis) — that breaks clipping and makes the shot look washed-out / “wrong theme”.

Verify: when the page overflows, image height must be **greater than** the viewport (e.g. desktop 1440×900 → height ≫ 900).

## 3. Host the images in a gist (do it this way or they won't render)

⚠️ The Gist REST API stores file `content` **literally** (no base64 decode), and `gh gist create` refuses binary files outright. Uploading a PNG via `gh api` therefore stores the base64 string as ASCII text: the raw URL serves `text/plain` and the image silently doesn't render. A gist is a git repository — push the binaries with git instead:

```bash
# 1) create a placeholder gist (text files ARE fine via the API)
GIST_ID=$(echo "screenshots" | gh gist create - -p -f README.md | grep -oE '[0-9a-f]{32}')

# 2) clone it with the gh token and push the real images
git clone "https://x-access-token:$(gh auth token)@gist.github.com/$GIST_ID.git" /tmp/gist-$GIST_ID
cp shot-desktop.png shot-mobile.png /tmp/gist-$GIST_ID/
cd /tmp/gist-$GIST_ID && git add -A && git commit -m "screenshots" && git push
HASH=$(git rev-parse HEAD)

# 3) embed in the PR description — pin the commit hash so CDN cache does not
#    keep serving an older PNG after you refresh the gist
#    https://gist.githubusercontent.com/<your-user>/<GIST_ID>/raw/<HASH>/shot-desktop.png
```

**Always verify before finishing** — this must return `200 image/png` and a `content-length` that matches the local file:

```bash
curl -sI "https://gist.githubusercontent.com/<your-user>/<GIST_ID>/raw/<HASH>/shot-desktop.png"
ls -l shot-desktop.png   # compare sizes
```

If it says `text/plain`, the "image" is text — re-push via git as above. If `content-length` is stale after an update, use the `/raw/<HASH>/...` form in the PR body (unpinned `/raw/shot-desktop.png` is CDN-cached ~5 minutes).

## 4. Embed in the PR description

Add a `## Screenshots` section with the raw gist URLs (commit-pinned), labelled desktop/mobile.

## 5. Role-guide documentation shots (committed PNGs)

When refreshing `docs/static/img/roles/*.png` or priming demo data so those pages are not empty, follow [`docs/AGENTS.md`](../../docs/AGENTS.md) instead of gist-hosting: login users, apply `docs/seed/role-screenshots.sql`, capture desktop full-page shots into the existing filenames, and commit them with the docs change.
