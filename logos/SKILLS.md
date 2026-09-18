# SKILLS.md — Logos Task Playbooks for AI Agents

Reusable, non-obvious procedures. Each skill says when to use it, then gives the exact steps.

## Skill: Gathering UI screenshots (for PRs and documentation)

**When to use**: any PR that changes `logos-ui/` (mandatory — see `AGENTS.md`), or when adding UI imagery to documentation. Reviewers must be able to see the result without running the stack; a UI PR without screenshots is not reviewable.

**Requirements**:
- At least one **desktop** screenshot of the changed view.
- At least one **mobile** screenshot (375px viewport) of the same view — the shared data tables drop their header below 768px and fall back to per-cell `data-label`s, so a mobile shot is the only way to see how a table actually renders there.
- **Every screenshot must show the FULL page** — page header, tab bar, and the entire scrollable content. A shot that starts mid-view or cuts off the last table row is not acceptable.
- Screenshots go into the PR description (or docs) only — **never commit them to the repository**.

### 1. Run the stack and log in

```bash
docker compose -f docker-compose.dev.yaml up --build   # from logos/
cd logos-ui && ng serve                                 # UI on http://localhost:4200/
```

Log in with a seeded Keycloak user (all passwords `password`), e.g. `tobias.wasner` (logos admin). See `README.md` for the full user table and team provisioning.

### 2. Capture a true full-page screenshot

The Logos UI scrolls inside an inner container, not the document — a plain full-page browser screenshot only captures the first viewport. When scripting the capture (Playwright), first unlock the scroll containers, then screenshot with `fullPage: true`:

- set `height: auto`, `max-height: none`, and `overflow: visible` (all `!important`) on the content root's ancestors up to `<html>`/`<body>`, **and**
- do the same on every element whose computed `overflow-y` is `auto` or `scroll`.

Verify the result: the image must be taller than the viewport whenever the page overflows.

### 3. Host the images in a gist (do it this way or they won't render)

⚠️ The Gist REST API stores file `content` **literally** (no base64 decode), and `gh gist create` refuses binary files outright. Uploading a PNG via `gh api` therefore stores the base64 string as ASCII text: the raw URL serves `text/plain` and the image silently doesn't render. A gist is a git repository — push the binaries with git instead:

```bash
# 1) create a placeholder gist (text files ARE fine via the API)
GIST_ID=$(echo "screenshots" | gh gist create - -p -f README.md | grep -oE '[0-9a-f]{32}')

# 2) clone it with the gh token and push the real images
git clone "https://x-access-token:$(gh auth token)@gist.github.com/$GIST_ID.git" /tmp/gist-$GIST_ID
cp shot-desktop.png shot-mobile.png /tmp/gist-$GIST_ID/
cd /tmp/gist-$GIST_ID && git add -A && git commit -m "screenshots" && git push

# 3) embed in the PR description
#    https://gist.githubusercontent.com/<your-user>/<GIST_ID>/raw/shot-desktop.png
```

**Always verify before finishing** — this must return `200 image/png`:

```bash
curl -sI https://gist.githubusercontent.com/<your-user>/<GIST_ID>/raw/shot-desktop.png
```

If it says `text/plain`, the "image" is text — re-push via git as above (the gist ID and PR URLs stay the same).

### 4. Embed in the PR description

Add a `## Screenshots` section with the raw gist URLs, one per line, labelled desktop/mobile.
