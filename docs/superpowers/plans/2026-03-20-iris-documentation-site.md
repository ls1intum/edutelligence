# Iris Documentation Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete Docusaurus documentation site for Iris with a polished landing page and content-rich multi-audience docs.

**Architecture:** Docusaurus 3.x static site in `iris/docs/`, following the same monorepo pattern as Atlas (`atlas/docs/`) and Athena (`athena/docs/`). Six sidebars (Overview, Student, Instructor, Developer, Admin, Research), custom landing page with Iris design system colors, GitHub Pages deployment via existing workflow.

**Tech Stack:** Docusaurus 3.x, TypeScript, React, CSS Modules, `@easyops-cn/docusaurus-search-local`

**Spec:** `docs/superpowers/specs/2026-03-20-iris-documentation-site-design.md`

**Reference implementations:**
- Athena docs: `/Users/pat/projects/edutelligence/athena/docs/` (config, sidebars, components)
- Atlas docs: `/Users/pat/projects/edutelligence/atlas/docs/` (config, GitHub Actions)
- Iris source: `/Users/pat/projects/claudeworktrees/edutelligence/feature-iris-NDocs/iris/` (content source)
- Artemis Iris docs (branch): `origin/feature/iris/improve-about-iris-links` in `~/projects/artemis/`
- Iris papers: `~/Downloads/` (3 PDFs — ITiCSE 2024, Koli Calling '25, C&E:AI 2026)

---

## File Structure

```
iris/docs/
├── docusaurus.config.ts          # Site config (url, baseUrl, navbar, theme, search, footer)
├── sidebars.ts                   # 6 sidebar definitions
├── package.json                  # Dependencies (docusaurus 3.x, search plugin)
├── tsconfig.json                 # TypeScript config
├── babel.config.js               # Babel config for Docusaurus
├── src/
│   ├── css/
│   │   └── custom.css            # Iris theme variables (light/dark), global overrides
│   ├── pages/
│   │   ├── index.tsx             # Landing page (hero, trust bar, features, comparison, research, quotes, quickstart, FAQ)
│   │   └── index.module.css      # Landing page styles (CSS Modules)
│   └── components/
│       └── home/                 # Section-oriented landing page components
│           ├── HeroSection.tsx
│           ├── TrustBar.tsx
│           ├── FeatureCards.tsx
│           ├── ComparisonSection.tsx
│           ├── ResearchHighlights.tsx
│           ├── StudentQuotes.tsx
│           ├── AudienceCards.tsx
│           ├── FaqSection.tsx
│           ├── EcosystemFooter.tsx
│           └── styles.module.css
├── docs/
│   ├── overview/                 # 4 pages
│   ├── student/                  # 9 pages
│   ├── instructor/               # 8 pages
│   ├── developer/                # 11 pages
│   ├── admin/                    # 6 pages
│   └── research/                 # 4 pages
└── static/
    └── img/
        ├── iris/                 # Logo PNGs (already copied)
        └── screenshots/          # .gitkeep (placeholders in docs)
```

---

## Task 1: Scaffold Docusaurus Project

**Files:**
- Create: `iris/docs/package.json`
- Create: `iris/docs/docusaurus.config.ts`
- Create: `iris/docs/sidebars.ts`
- Create: `iris/docs/tsconfig.json`
- Create: `iris/docs/babel.config.js`
- Create: `iris/docs/src/css/custom.css`
- Create: `iris/docs/static/img/screenshots/.gitkeep`
- Verify: `iris/docs/static/img/iris/` (logos already present)

**Reference:** Copy structure from `athena/docs/` and adapt for Iris.

- [ ] **Step 1: Create package.json**

```json
{
  "name": "iris-docs",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "docusaurus": "docusaurus",
    "start": "docusaurus start",
    "build": "docusaurus build",
    "swizzle": "docusaurus swizzle",
    "deploy": "docusaurus deploy",
    "clear": "docusaurus clear",
    "serve": "docusaurus serve"
  },
  "dependencies": {
    "@docusaurus/core": "3.9.2",
    "@docusaurus/preset-classic": "3.9.2",
    "@easyops-cn/docusaurus-search-local": "^0.52.1",
    "@mdx-js/react": "^3.0.0",
    "clsx": "^2.0.0",
    "prism-react-renderer": "^2.3.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@docusaurus/module-type-aliases": "3.9.2",
    "@docusaurus/tsconfig": "3.9.2",
    "@docusaurus/types": "3.9.2",
    "typescript": "~5.6.0"
  },
  "engines": {
    "node": ">=20.0"
  }
}
```

- [ ] **Step 2: Create docusaurus.config.ts**

Model after Athena's config. Key settings:
```typescript
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Iris',
  tagline: 'The AI tutor that teaches, not just answers',
  favicon: 'img/iris/iris-logo-small.png',
  url: 'https://ls1intum.github.io',
  baseUrl: '/edutelligence/iris/',
  organizationName: 'ls1intum',
  projectName: 'edutelligence',
  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',
  i18n: { defaultLocale: 'en', locales: ['en'] },
  presets: [['classic', {
    docs: { sidebarPath: './sidebars.ts', editUrl: 'https://github.com/ls1intum/edutelligence/tree/main/iris/docs/' },
    blog: false,
    theme: { customCss: './src/css/custom.css' },
  }]],
  plugins: [
    ['@easyops-cn/docusaurus-search-local', {
      hashed: true,
      language: ['en'],
      docsRouteBasePath: ['docs'],
      docsDir: ['docs/overview', 'docs/student', 'docs/instructor', 'docs/developer', 'docs/admin', 'docs/research'],
      indexBlog: false,
      searchContextByPaths: [
        { label: { en: 'Overview' }, path: 'docs/overview' },
        { label: { en: 'Student Guide' }, path: 'docs/student' },
        { label: { en: 'Instructor Guide' }, path: 'docs/instructor' },
        { label: { en: 'Developer Guide' }, path: 'docs/developer' },
        { label: { en: 'Admin Guide' }, path: 'docs/admin' },
        { label: { en: 'Research' }, path: 'docs/research' },
      ],
      hideSearchBarWithNoSearchContext: true,
      useAllContextsWithNoSearchContext: false,
      highlightSearchTermsOnTargetPage: true,
      searchResultContextMaxLength: 60,
    }],
  ],
  themeConfig: {
    image: 'img/iris/iris-logo-big-right.png',
    navbar: {
      title: 'Iris',
      logo: { alt: 'Iris Logo', src: 'img/iris/iris-logo-small.png' },
      items: [
        { type: 'docSidebar', sidebarId: 'overviewSidebar', position: 'left', label: 'Overview' },
        { type: 'docSidebar', sidebarId: 'studentSidebar', position: 'left', label: 'Student Guide' },
        { type: 'docSidebar', sidebarId: 'instructorSidebar', position: 'left', label: 'Instructor Guide' },
        { type: 'docSidebar', sidebarId: 'developerSidebar', position: 'left', label: 'Developer Guide' },
        { type: 'docSidebar', sidebarId: 'adminSidebar', position: 'left', label: 'Admin Guide' },
        { type: 'docSidebar', sidebarId: 'researchSidebar', position: 'left', label: 'Research' },
        { type: 'search', position: 'right' },
        { href: 'https://github.com/ls1intum/edutelligence', label: 'GitHub', position: 'right' },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        { title: 'Guides', items: [
          { label: 'Student Guide', to: '/docs/student/getting-started' },
          { label: 'Instructor Guide', to: '/docs/instructor/enabling-iris' },
          { label: 'Developer Guide', to: '/docs/developer/local-setup' },
        ]},
        { title: 'Community', items: [
          { label: 'GitHub', href: 'https://github.com/ls1intum/edutelligence' },
          { label: 'Artemis', href: 'https://github.com/ls1intum/Artemis' },
        ]},
        { title: 'Research', items: [
          { label: 'Publications', to: '/docs/research/publications' },
          { label: 'Citing Iris', to: '/docs/research/citing-iris' },
        ]},
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Technical University of Munich. Built with Docusaurus.`,
    },
    colorMode: { defaultMode: 'light', respectPrefersColorScheme: true },
  } satisfies Preset.ThemeConfig,
};
export default config;
```

- [ ] **Step 3: Create sidebars.ts**

```typescript
import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  overviewSidebar: [
    { type: 'doc', id: 'overview/what-is-iris', label: 'What is Iris?' },
    { type: 'doc', id: 'overview/architecture', label: 'Architecture' },
    { type: 'doc', id: 'overview/ecosystem', label: 'EduTelligence Ecosystem' },
    { type: 'doc', id: 'overview/compatibility', label: 'Compatibility' },
  ],
  studentSidebar: [
    { type: 'doc', id: 'student/getting-started', label: 'Getting Started' },
    { type: 'doc', id: 'student/course-chat', label: 'Course Chat' },
    { type: 'doc', id: 'student/exercise-chat', label: 'Exercise Chat' },
    { type: 'doc', id: 'student/text-exercise-chat', label: 'Text Exercise Chat' },
    { type: 'doc', id: 'student/lecture-chat', label: 'Lecture Chat' },
    { type: 'doc', id: 'student/how-iris-helps', label: 'How Iris Helps You Learn' },
    { type: 'doc', id: 'student/memory', label: 'Memory' },
    { type: 'doc', id: 'student/privacy', label: 'Privacy & Data' },
    { type: 'doc', id: 'student/tips', label: 'Tips for Effective Use' },
  ],
  instructorSidebar: [
    { type: 'doc', id: 'instructor/enabling-iris', label: 'Enabling Iris' },
    { type: 'doc', id: 'instructor/custom-instructions', label: 'Custom Instructions' },
    { type: 'doc', id: 'instructor/variants', label: 'Variants' },
    { type: 'doc', id: 'instructor/rate-limits', label: 'Rate Limits' },
    { type: 'doc', id: 'instructor/lecture-ingestion', label: 'Lecture Ingestion' },
    { type: 'doc', id: 'instructor/faq-ingestion', label: 'FAQ Ingestion' },
    { type: 'doc', id: 'instructor/tutor-suggestions', label: 'Tutor Suggestions' },
    { type: 'doc', id: 'instructor/pedagogical-approach', label: 'Pedagogical Approach' },
  ],
  developerSidebar: [
    { type: 'doc', id: 'developer/local-setup', label: 'Local Setup' },
    { type: 'doc', id: 'developer/project-structure', label: 'Project Structure' },
    { type: 'doc', id: 'developer/pipeline-system', label: 'Pipeline System' },
    { type: 'doc', id: 'developer/variant-system', label: 'Variant System' },
    { type: 'doc', id: 'developer/tools', label: 'Tools' },
    { type: 'doc', id: 'developer/prompts', label: 'Prompts' },
    { type: 'doc', id: 'developer/rag-pipeline', label: 'RAG Pipeline' },
    { type: 'doc', id: 'developer/domain-models', label: 'Domain Models' },
    { type: 'doc', id: 'developer/configuration', label: 'Configuration' },
    { type: 'doc', id: 'developer/testing', label: 'Testing' },
    { type: 'doc', id: 'developer/contributing', label: 'Contributing' },
  ],
  adminSidebar: [
    { type: 'doc', id: 'admin/deployment', label: 'Deployment' },
    { type: 'doc', id: 'admin/artemis-integration', label: 'Artemis Integration' },
    { type: 'doc', id: 'admin/llm-configuration', label: 'LLM Configuration' },
    { type: 'doc', id: 'admin/weaviate-setup', label: 'Weaviate Setup' },
    { type: 'doc', id: 'admin/monitoring', label: 'Monitoring' },
    { type: 'doc', id: 'admin/troubleshooting', label: 'Troubleshooting' },
  ],
  researchSidebar: [
    { type: 'doc', id: 'research/pedagogical-design', label: 'Pedagogical Design' },
    { type: 'doc', id: 'research/study-results', label: 'Study Results' },
    { type: 'doc', id: 'research/publications', label: 'Publications' },
    { type: 'doc', id: 'research/citing-iris', label: 'Citing Iris' },
  ],
};
export default sidebars;
```

- [ ] **Step 4: Create tsconfig.json and babel.config.js**

tsconfig.json — copy from Athena's `athena/docs/tsconfig.json`.
babel.config.js — standard Docusaurus:
```js
module.exports = { presets: [require.resolve('@docusaurus/core/lib/babel/preset')] };
```

- [ ] **Step 5: Create custom.css with Iris theme**

Derive all colors from the Iris chatbot component (spec Section 3). Include both light and dark mode. Use DM Sans + DM Serif Display + JetBrains Mono via Google Fonts import.

Reference values:
- Light primary: `#3e8acc`, dark primary: `#5a9fd6`
- Light bg: `#ffffff`, dark bg: `#181a18`
- Light surface: `#f8f9fa`, dark surface: `#1f2320`
- Light text: `#212529`, dark text: `#f8f9fa`
- Light border: `#dee2e6`, dark border: `#3a3a3a`
- See spec Section 3 for full color table

- [ ] **Step 6: Copy logo assets into the docs static directory**

```bash
mkdir -p iris/docs/static/img/iris
cp iris/docs/../../../docs/static/img/iris/*.png iris/docs/static/img/iris/ 2>/dev/null || \
cp ~/projects/artemis/src/main/resources/public/images/iris/*.png iris/docs/static/img/iris/
```

Verify all 3 PNGs exist: `iris-logo-small.png`, `iris-logo-big-right.png`, `iris-logo-big-left.png`.

- [ ] **Step 7: Create placeholder docs for every sidebar entry**

Create all 42 markdown files as stubs with frontmatter:
```markdown
---
title: Page Title
---

# Page Title

Content coming in subsequent tasks.
```

This ensures the build succeeds and all sidebar links resolve.

- [ ] **Step 8: Run npm install and verify build succeeds**

```bash
cd iris/docs && npm install && npm run build
```

Expected: Clean build with no broken links. This is the first build gate — it should pass now that stubs and assets are in place.

- [ ] **Step 9: Commit**

```bash
git add iris/docs/
git commit -m "Iris: Scaffold Docusaurus documentation site

Initializes the Iris docs site with Docusaurus 3.x, six sidebar
definitions (Overview, Student, Instructor, Developer, Admin, Research),
Iris theme colors, search plugin, and stub pages for all 42 doc entries."
```

---

## Task 2: Landing Page

**Files:**
- Create: `iris/docs/src/pages/index.tsx`
- Create: `iris/docs/src/pages/index.module.css`
- Create: `iris/docs/src/components/home/HeroSection.tsx`
- Create: `iris/docs/src/components/home/TrustBar.tsx`
- Create: `iris/docs/src/components/home/FeatureCards.tsx`
- Create: `iris/docs/src/components/home/ComparisonSection.tsx`
- Create: `iris/docs/src/components/home/ResearchHighlights.tsx`
- Create: `iris/docs/src/components/home/StudentQuotes.tsx`
- Create: `iris/docs/src/components/home/AudienceCards.tsx`
- Create: `iris/docs/src/components/home/FaqSection.tsx`
- Create: `iris/docs/src/components/home/EcosystemFooter.tsx`
- Create: `iris/docs/src/components/home/styles.module.css`

**Reference:** Spec Section 4 (all 10 subsections). Athena's landing page for structural reference (`athena/docs/src/pages/index.tsx`). Use Direction B layout with Direction A copy.

- [ ] **Step 1: Create section-oriented landing page components**

One component per landing page section under `src/components/home/`:
- `HeroSection` — mascot, headline, subtitle, CTAs
- `TrustBar` — 4 horizontal trust items
- `FeatureCards` — 3 feature cards (Calibrated Scaffolding, Context-Aware, RAG-Grounded)
- `ComparisonSection` — side-by-side generic chatbot vs Iris
- `ResearchHighlights` — stats row from RCT
- `StudentQuotes` — quotes from Koli Calling study
- `AudienceCards` — 4 quickstart cards linking to guides
- `FaqSection` — 5 expandable FAQ items
- `EcosystemFooter` — EduTelligence service overview

Shared styles in `styles.module.css`. Follow the Iris color system from custom.css variables.

- [ ] **Step 2: Create landing page (index.tsx)**

Implement all 10 sections from spec Section 4 in order:
1. Hero (centered, mascot, headline, subtitle, CTAs)
2. Trust bar (4 items horizontal)
3. Feature cards (3 cards — Calibrated Scaffolding, Context-Aware, RAG-Grounded)
4. How Iris is Different (side-by-side comparison: generic chatbot vs Iris)
5. Research highlights (stats row: 275 students, +0.55 Cohen's d, −0.81 frustration, 3 papers)
6. Student quotes (from Koli Calling qualitative study)
7. Screencast placeholder (video embed area with guidance text)
8. Audience quickstart (4 cards: Student, Instructor, Developer, Admin)
9. FAQ (5 expandable items from spec)
10. EduTelligence ecosystem footer

Use the landing page copy exactly as specified. Do NOT use generic placeholder text.

- [ ] **Step 3: Style the landing page (index.module.css)**

Key design decisions:
- DM Serif Display for the hero headline only
- DM Sans for everything else
- Iris blue (`#3e8acc`) as primary accent
- Clean white background (light mode), `#0e100e` dark background
- Feature cards with `#f8f9fa` background, `8px` border radius
- Stats with DM Serif Display for numbers
- Full dark mode support using `[data-theme='dark']` selectors
- Responsive: stack to single column on mobile
- Hover effects: subtle lift (`translateY(-4px)`) on cards, like Athena
- Max content width ~1100px, centered

Follow the frontend-design skill guidelines: avoid generic AI aesthetics, use the Iris color system intentionally, make the comparison section the memorable differentiator.

- [ ] **Step 4: Verify build and visual check**

```bash
cd iris/docs && npm run build && npm run serve
```

Open in browser, check both light and dark mode. Verify all sections render, links work, responsive layout works.

- [ ] **Step 5: Commit**

```bash
git add iris/docs/src/
git commit -m "Iris: Add landing page with hero, features, research highlights, and FAQ

Product-forward landing page with Iris design system colors, research-backed
proof points from the 275-student RCT, student quotes, audience quickstart
cards, and FAQ section. Supports light and dark mode."
```

---

## Task 3: Overview Documentation

**Files:**
- Modify: `iris/docs/docs/overview/what-is-iris.md`
- Modify: `iris/docs/docs/overview/architecture.md`
- Modify: `iris/docs/docs/overview/ecosystem.md`
- Modify: `iris/docs/docs/overview/compatibility.md`

**Sources:**
- ITiCSE 2024 paper (intro, Section 3)
- About Iris modal content (from Artemis branch `origin/feature/iris/improve-about-iris-links`)
- Iris README.MD (compatibility matrix)
- Artemis admin docs (`~/projects/artemis/documentation/docs/admin/artemis-intelligence.mdx`)
- Code exploration results (architecture details)

- [ ] **Step 1: Write "What is Iris?"**

Content structure:
- What Iris is (1 paragraph — from ITiCSE abstract + About Iris modal)
- Key capabilities (calibrated scaffolding, context-awareness, RAG grounding — non-technical language)
- What makes Iris different from ChatGPT (brief, factual — from C&E:AI findings)
- Who uses Iris (students, instructors, admins, researchers)
- `:::info Screenshot Needed — About Iris modal in Artemis showing features and expectations :::`

- [ ] **Step 2: Write "Architecture"**

Content structure:
- High-level overview (Artemis sends request → Iris pipeline processes → LLM generates → status callback returns)
- Pipeline system overview (what pipelines are, how they work at a conceptual level)
- Agent execution flow (tools, RAG, response generation)
- `:::info Screenshot Needed — Architecture diagram — Artemis → Iris → LLM with tool calls and RAG :::`
- `:::info Screenshot Needed — Pipeline execution flow diagram :::`

Keep it conceptual — developer-level details go in the Developer Guide.

- [ ] **Step 3: Write "EduTelligence Ecosystem"**

Content structure:
- What is EduTelligence (the suite of AI services for Artemis)
- Service overview table: Iris, Athena, Memiris, Atlas, Nebula, Logos — name, purpose, status
- How Iris interacts with other services (especially Memiris for memory, Artemis as host)
- Links to other services' docs

Source: Artemis intelligence docs at `origin/feature/iris/improve-about-iris-links:documentation/docs/admin/artemis-intelligence.mdx`

- [ ] **Step 4: Write "Compatibility"**

Content structure:
- Artemis version compatibility matrix (from Iris README)
- Version table: Artemis version ↔ Iris version
- How to check version compatibility

- [ ] **Step 5: Verify build**

```bash
cd iris/docs && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add iris/docs/docs/overview/
git commit -m "Iris: Add Overview documentation (What is Iris, Architecture, Ecosystem, Compatibility)"
```

---

## Task 4: Student Guide Documentation

**Files:**
- Modify: All 9 files in `iris/docs/docs/student/`

**Primary source:** Artemis student docs from branch `origin/feature/iris/improve-about-iris-links`. Use `git show origin/feature/iris/improve-about-iris-links:documentation/docs/student/learning-content/iris.mdx` to get the full content.

**Additional sources:** About Iris modal, ITiCSE paper Section 3, C&E:AI paper Section 3.1

- [ ] **Step 1: Write "Getting Started"**

Pull from Artemis student docs: AI experience selection (Cloud, On-premise, No AI), where to find Iris in Artemis.
- `:::info Screenshot Needed — AI experience selection screen :::`

- [ ] **Step 2: Write "Course Chat"**

How Course Chat works: asking about lectures, concepts, course content. How Iris retrieves from slides and transcriptions. Citations.
- `:::info Screenshot Needed — Course chat conversation with citation :::`

- [ ] **Step 3: Write "Exercise Chat"**

Programming exercise support: automatic context reading (code, build logs, test results), calibrated hints.
- `:::info Screenshot Needed — Exercise chat showing context-aware response :::`

- [ ] **Step 4: Write "Text Exercise Chat"**

Text exercise support: how Iris helps with essay/text-based exercises, scaffolded guidance for writing and structuring arguments.

- [ ] **Step 5: Write "Lecture Chat"**

Lecture-specific questions: how Iris retrieves from specific lecture slides and transcripts.
- `:::info Screenshot Needed — Lecture chat with transcript-based retrieval :::`

- [ ] **Step 6: Write "How Iris Helps You Learn"**

The 4-tier scaffolding system (from C&E:AI paper Section 3.1):
1. Subtle hints — focus attention on salient code lines or conceptual blind spots
2. Guiding questions — provoke reflection and self-discovery
3. High-level conceptual feedback — strategic guidance without revealing implementations
4. Generalized examples — illustrate analogous patterns while keeping the target solution opaque

Also cover: citations, follow-up suggestions, proactive hints.

- [ ] **Step 7: Write "Memory"**

Memiris integration: what Iris remembers, how it personalizes across sessions, managing/deleting memory data.

- [ ] **Step 8: Write "Privacy & Data"**

Cloud vs. on-premise data handling (from About Iris modal), GDPR considerations, what data is sent to LLMs.

- [ ] **Step 9: Write "Tips for Effective Use"**

Practical advice: how to ask good questions, when to use which chat type (course vs exercise vs lecture), what Iris can and can't help with, how to make the most of scaffolded hints.

- [ ] **Step 10: Verify build**

```bash
cd iris/docs && npm run build
```

- [ ] **Step 11: Commit**

```bash
git add iris/docs/docs/student/
git commit -m "Iris: Add Student Guide documentation (9 pages)

Comprehensive student-facing docs covering getting started, course/exercise/
text/lecture chat, scaffolding system, memory, privacy, and usage tips."
```

---

## Task 5: Instructor Guide Documentation

**Files:**
- Modify: All 8 files in `iris/docs/docs/instructor/`

**Sources:**
- Artemis instructor docs: `~/projects/artemis/documentation/docs/instructor/course-management/course-configuration.mdx` (Iris settings)
- Artemis instructor docs: `~/projects/artemis/documentation/docs/instructor/lectures/lectures.mdx` (lecture ingestion)
- Artemis instructor docs: `~/projects/artemis/documentation/docs/instructor/communication-support/communication.mdx` (tutor suggestions)
- Artemis branch: `origin/feature/iris/improve-about-iris-links` for updated content
- C&E:AI paper Section 3 (pedagogical approach)
- ITiCSE paper Section 3 (pedagogical approach)
- Code: `iris/src/iris/domain/variant/` (variant system), pipeline VARIANT_DEFS

- [ ] **Step 1: Write "Enabling Iris"**

Course-level settings: how to enable/disable Iris, IrisCourseSettings.
- `:::info Screenshot Needed — Iris course settings panel in Artemis :::`

- [ ] **Step 2: Write "Custom Instructions"**

How to write custom instructions for Iris behavior in a specific course. Max length, best practices, examples.

- [ ] **Step 3: Write "Variants"**

Default vs. Advanced variants: what they are, when to use each, quality/cost tradeoffs.

- [ ] **Step 4: Write "Rate Limits"**

Per-course rate limiting: configuration, default values, why rate limits exist.

- [ ] **Step 5: Write "Lecture Ingestion"**

Sending lecture slides and transcriptions to Iris: bulk ingestion, individual unit ingestion.
- `:::info Screenshot Needed — Lecture management page with Iris ingestion buttons :::`

- [ ] **Step 6: Write "FAQ Ingestion"**

Ingesting course FAQs into Iris's knowledge base.

- [ ] **Step 7: Write "Tutor Suggestions"**

AI-powered suggestions for tutors in discussion threads. Direct Iris conversations from threads.
- `:::info Screenshot Needed — Tutor suggestion in a discussion thread :::`

- [ ] **Step 8: Write "Pedagogical Approach"**

The philosophy behind Iris: why scaffolding over solutions, Cognitive Load Theory, Self-Determination Theory, Zone of Proximal Development. Reference the research findings factually.

- [ ] **Step 9: Verify build and commit**

```bash
cd iris/docs && npm run build
git add iris/docs/docs/instructor/
git commit -m "Iris: Add Instructor Guide documentation (8 pages)

Covers enabling Iris, custom instructions, variants, rate limits, lecture/FAQ
ingestion, tutor suggestions, and the pedagogical approach behind Iris."
```

---

## Task 6: Developer Guide Documentation

**Files:**
- Modify: All 11 files in `iris/docs/docs/developer/`

**Sources:**
- Iris README.MD (local setup, troubleshooting)
- `iris/src/iris/` source code (all developer docs)
- `iris/application.example.yml` and `iris/llm_config.example.yml`
- `iris/COURSE_CHAT_PIPELINE_REFACTORING.md` (variant system history)
- `iris/pyproject.toml` (dependencies, tooling)

- [ ] **Step 1: Write "Local Setup"**

Pull from README: prerequisites (Python 3.12+, Poetry, Docker), installation steps, Docker Compose for Weaviate, configuration files, running locally with `poetry run python -m iris.main`, troubleshooting.

- [ ] **Step 2: Write "Project Structure"**

Directory layout with descriptions of each major directory and key files. Reference the exploration findings from the spec (Section 10).

- [ ] **Step 3: Write "Pipeline System"**

Pipeline base class (`iris/src/iris/pipeline/pipeline.py`): `PIPELINE_ID`, `ROLES`, `VARIANT_DEFS`, `DEPENDENCIES`, `__call__`. AbstractAgentPipeline: agent execution flow, tool creation, message handling, status callbacks. SubPipeline for internal pipelines. How to create a new pipeline (step-by-step).

- [ ] **Step 4: Write "Variant System"**

Variant class (`iris/src/iris/domain/variant/variant.py`): `model(role, local)` method. How pipelines declare variants via class attributes. How the request handler resolves models. Cloud vs. local model selection.

- [ ] **Step 5: Write "Tools"**

The tool system in `iris/src/iris/tools/`: how tools are LLM-callable functions, tool schema, how agents select tools dynamically. List of available tools with descriptions. How to create a new tool.

- [ ] **Step 6: Write "Prompts"**

Jinja2 templates in `iris/src/iris/pipeline/prompts/`: how system prompts are assembled, how context is injected, template variables, prompt design patterns.

- [ ] **Step 7: Write "RAG Pipeline"**

Ingestion: PDF parsing (PyMuPDF) → chunking → Weaviate storage. Collections (LectureUnitPageChunk, LectureTranscription, FAQ, etc.). Retrieval: query rewriting → HyDE → multi-source concurrent retrieval → reranking (Cohere). Citation generation with `cite-only` directive.

- [ ] **Step 8: Write "Domain Models"**

DTO hierarchy: ChatPipelineExecutionDTO, IngestionPipelineExecutionDto, data models (CourseDTO, ProgrammingExerciseDTO, etc.). Data flow between Artemis and Iris. Pydantic validation.

- [ ] **Step 9: Write "Configuration"**

Deep dive into `application.yml` and `llm_config.yml`: all configuration options explained with examples. Environment variables. Configuration loading in `config.py`.

- [ ] **Step 10: Write "Testing" and "Contributing"**

Testing: how to run tests (`poetry run pytest`), test structure, coverage. Contributing: code style (pylint, black, isort), pre-commit hooks, PR process, branch naming.

- [ ] **Step 11: Verify build and commit**

```bash
cd iris/docs && npm run build
git add iris/docs/docs/developer/
git commit -m "Iris: Add Developer Guide documentation (11 pages)

Comprehensive developer docs covering local setup, project structure, pipeline
system, variant system, tools, prompts, RAG pipeline, domain models,
configuration, testing, and contributing guidelines."
```

---

## Task 7: Admin Guide Documentation

**Files:**
- Modify: All 6 files in `iris/docs/docs/admin/`

**Sources:**
- Iris README.MD (Docker, setup)
- `iris/application.example.yml` and `iris/llm_config.example.yml`
- Artemis admin docs: `~/projects/artemis/documentation/docs/admin/extension-services.mdx`
- Code: `iris/src/iris/sentry.py`, `iris/src/iris/tracing/langfuse_tracer.py`
- Code: `iris/src/iris/vector_database/database.py`

- [ ] **Step 1: Write "Deployment"**

Docker deployment: Dockerfile, docker-compose, production configuration, resource requirements, health endpoint.

- [ ] **Step 2: Write "Artemis Integration"**

Connecting Iris to Artemis: configuration in `application-artemis.yml` (`iris.enabled`, `iris.url`, `iris.secret-token`), health checks, troubleshooting connectivity.

- [ ] **Step 3: Write "LLM Configuration"**

`llm_config.yml` deep dive: model types (openai_chat, azure_chat, ollama, openai_embedding, cohere_azure), required fields per type, cost tracking, example configurations for OpenAI, Azure, Ollama.

- [ ] **Step 4: Write "Weaviate Setup"**

Weaviate deployment: Docker, configuration (host, port, grpc_port), collection management, data persistence.

- [ ] **Step 5: Write "Monitoring" and "Troubleshooting"**

Monitoring: Sentry setup, LangFuse LLM tracing setup, APScheduler background jobs. Troubleshooting: common issues from README, connectivity problems, LLM configuration errors.

- [ ] **Step 6: Verify build and commit**

```bash
cd iris/docs && npm run build
git add iris/docs/docs/admin/
git commit -m "Iris: Add Admin Guide documentation (6 pages)

Covers deployment, Artemis integration, LLM configuration, Weaviate setup,
monitoring (Sentry, LangFuse), and troubleshooting."
```

---

## Task 8: Research Documentation

**Files:**
- Modify: All 4 files in `iris/docs/docs/research/`

**Sources:**
- ITiCSE 2024 paper (`3649217.3653543.pdf`)
- Koli Calling '25 paper (`3769994.3770025.pdf`)
- C&E:AI 2026 paper (`1-s2.0-S2666920X25001778-main.pdf`)

- [ ] **Step 1: Write "Pedagogical Design"**

The 3 architectural pillars (from C&E:AI Section 3):
1. Educational scaffolding via calibrated hints (4-tier system)
2. Context-aware dynamic agent architecture
3. Multimodal RAG pipeline

Theoretical foundations: Cognitive Load Theory, Self-Determination Theory, Zone of Proximal Development, scaffolding research.

- [ ] **Step 2: Write "Study Results"**

Factual presentation of findings from all 3 studies:

**ITiCSE 2024 (N=121):** Survey results on perceived effectiveness, comfort, reliance. Key finding: students perceive Iris positively and feel comfortable asking questions.

**Koli Calling '25 (N=33):** Mixed-methods study. Qualitative themes: context awareness universally valued, time pressure drives tool selection, individual scaffolding preferences vary, over-reliance concerns stronger for ChatGPT.

**C&E:AI 2026 (N=275):** Large RCT findings:
- Both AI tools boost exercise performance but not learning gains
- Only Iris increases intrinsic motivation (+0.55 Cohen's d vs No AI)
- Both reduce frustration (−0.81 Iris vs No AI)
- ChatGPT perceived as easier but creates a "comfort trap"
- Iris preserves performance variation (scaffolding balances support and challenge)

Present data factually. Acknowledge limitations from each paper.

- [ ] **Step 3: Write "Publications"**

Full citations with DOI links for all 3 papers. BibTeX entries for each.

- [ ] **Step 4: Write "Citing Iris"**

Recommended citation (ITiCSE 2024 as the primary system paper). BibTeX for copy-paste. How to reference specific aspects (scaffolding design → C&E:AI, qualitative findings → Koli Calling).

- [ ] **Step 5: Verify build and commit**

```bash
cd iris/docs && npm run build
git add iris/docs/docs/research/
git commit -m "Iris: Add Research documentation (4 pages)

Documents the pedagogical design, study results from 3 peer-reviewed papers
(ITiCSE 2024, Koli Calling '25, C&E:AI 2026), publications list with BibTeX,
and citation guidance."
```

---

## Task 9: GitHub Actions Deployment

**Files:**
- Create: `.github/workflows/iris_docs-build.yml`
- Modify: `.github/workflows/docs.yml`

**Reference:** Existing workflows `athena_docs-build.yml` and `atlas_docs-build.yml` in the main repo at `~/projects/edutelligence/.github/workflows/`.

- [ ] **Step 1: Create iris_docs-build.yml**

Mirror `athena_docs-build.yml` structure:
- `workflow_call` trigger
- Detect changes in `iris/docs/**`
- Node.js 24 setup (matching Athena's workflow)
- `npm ci` and `npm run build` in `iris/docs/`
- Cache `iris/docs/build`
- Upload artifact `iris-docs` with 1-day retention

Read the Athena workflow first to match the exact structure: `~/projects/edutelligence/.github/workflows/athena_docs-build.yml`

- [ ] **Step 2: Update docs.yml**

Add to the main deployment workflow:
- New `build-iris` job calling `iris_docs-build.yml`
- Add `build-iris` to `needs` array of the deploy job
- Download `iris-docs` artifact into `site/iris`
- Add Iris link to the monorepo landing page HTML

Read the current `docs.yml` first: `~/projects/edutelligence/.github/workflows/docs.yml`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/iris_docs-build.yml .github/workflows/docs.yml
git commit -m "Iris: Add GitHub Actions workflow for docs deployment

Adds iris_docs-build.yml and updates docs.yml to include Iris in the
combined GitHub Pages deployment at /edutelligence/iris/."
```

---

## Task 10: Final Polish & Build Verification

**Files:**
- Possibly modify: any file that has build warnings or issues

- [ ] **Step 1: Full clean build**

```bash
cd iris/docs && rm -rf build .docusaurus && npm run build 2>&1
```

Fix any warnings or errors.

- [ ] **Step 2: Local serve and visual review**

```bash
cd iris/docs && npm run serve
```

Check:
- Landing page renders correctly (all 10 sections) in both light and dark mode
- All navbar links work
- All sidebar navigation works
- Search returns results from different sections
- Mobile responsiveness
- No broken images (logos load)
- Footer links work

- [ ] **Step 3: Verify gitignore**

Ensure `iris/docs/node_modules/`, `iris/docs/build/`, `iris/docs/.docusaurus/` are gitignored. Check the repo-level `.gitignore` or add a local one.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add iris/docs/  # stage specific fixed files
git commit -m "Iris: Fix docs build warnings and polish"
```
