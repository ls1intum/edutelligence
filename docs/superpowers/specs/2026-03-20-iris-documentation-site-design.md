# Iris Documentation Site — Design Spec

**Date:** 2026-03-20
**Author:** Pat (with Claude)
**Status:** Approved

---

## 1. Overview

Build a Docusaurus documentation site for Iris, the AI virtual tutor integrated into Artemis. The site serves multiple audiences (students, instructors, developers, admins, researchers) with a polished marketing-style landing page and comprehensive, content-rich documentation pages.

### Goals
- A compelling landing page that showcases Iris's unique value (product-forward with research backing)
- Multi-audience documentation populated with real content from existing sources
- Consistent with the EduTelligence monorepo deployment pattern (GitHub Pages)
- Significantly better than Athena's docs and competitively superior to OneTutor

### Non-Goals
- Custom Docusaurus plugins or complex interactive features
- Video production (placeholder provided with screencast guidance)
- Screenshot capture (placeholder boxes with capture instructions)

---

## 2. Deployment & Infrastructure

### URL & Hosting
- **URL:** `https://ls1intum.github.io/edutelligence/iris/`
- **Hosting:** GitHub Pages (same as Atlas and Athena)
- **Future:** Possible CNAME to `iris.cit.tum.de` or similar

### Docusaurus Configuration
```typescript
url: 'https://ls1intum.github.io',
baseUrl: '/edutelligence/iris/',
organizationName: 'ls1intum',
projectName: 'edutelligence',
```

### GitHub Actions
- New `iris_docs-build.yml` workflow mirroring `atlas_docs-build.yml` and `athena_docs-build.yml`
- Triggers on changes to `iris/docs/**`
- Update `docs.yml` to add `build-iris` job and include Iris in combined deployment
- Add Iris link to the monorepo landing page at `ls1intum.github.io/edutelligence/`

### Tech Stack
- Docusaurus 3.x with TypeScript config
- Node 20+
- `@easyops-cn/docusaurus-search-local` with per-sidebar context filtering
- DM Sans (body) + DM Serif Display (landing headline only) via Google Fonts
- JetBrains Mono for code blocks

---

## 3. Visual Design

### Brand Identity
- **Tone:** Product-forward (B) with research backing (A), open-source community presence (C)
- **No overclaiming:** State facts from papers, never "the only" or unverifiable superlatives
- **Audience-neutral language:** Iris helps with all course content, not just programming

### Color System (from Iris chatbot component)

| Token | Light Mode | Dark Mode |
|-------|-----------|-----------|
| `--ifm-color-primary` | `#3e8acc` | `#5a9fd6` |
| `--ifm-background-color` | `#ffffff` | `#181a18` |
| `--ifm-background-surface-color` | `#f8f9fa` | `#1f2320` |
| `--ifm-font-color-base` | `#212529` | `#f8f9fa` |
| Border color | `#dee2e6` | `#3a3a3a` |
| Tertiary background | `#e9ecef` | `#262a27` |
| Accent background | `#dee2e6` | `#2d312e` |
| Label/secondary text | `#6c757d` | `#888888` |
| Success/green accent | `#28a745` | `#00bc8c` |

### Design Tokens
- **Border radius:** `8px` standard (matching chatbot `--radius-md`)
- **Border radius pill:** `999px` (badges, tags)
- **Shadow (mascot):** `drop-shadow(0 3px 8px rgba(0,0,0,0.24))`
- **Chat header shadow:** `0 10px 10px -15px rgba(0,0,0,0.3)`

### Typography
- **Body:** DM Sans, 400/500/600/700
- **Landing headline:** DM Serif Display
- **Code:** JetBrains Mono 400/500

### Logo Assets
- `static/img/iris/iris-logo-small.png` (279×256, forward-facing)
- `static/img/iris/iris-logo-big-right.png` (557×512, right-facing)
- `static/img/iris/iris-logo-big-left.png` (557×512, left-facing)
- PNG only, no SVG available. Single color variant (blue with green/yellow eyes).

---

## 4. Landing Page Structure

### 4.1 Hero Section
- **Layout:** Centered (Direction B)
- **Mascot:** Iris logo above headline
- **Headline:** "The AI tutor that teaches, not just *answers*"
- **Subtitle:** "Iris is a context-aware virtual tutor integrated into Artemis. It provides scaffolded hints, guided learning, and grounded responses — designed to preserve productive struggle and foster genuine understanding."
- **CTAs:** "Get Started" (primary) + "View on GitHub" (ghost)

### 4.2 Trust Bar
Horizontal strip below hero:
- "Integrated into Artemis at TUM"
- "1,600+ active students"
- "Open Source"
- "Peer-Reviewed Research"

### 4.3 Feature Cards
3 cards with specific (not generic) language:
1. **Calibrated Scaffolding** — "Four tiers of support — from subtle hints to generalized examples — preserving productive struggle instead of giving away answers."
2. **Context-Aware** — "Deeply integrated into Artemis. Iris reads your code, build logs, test results, and course materials automatically — no copy-pasting needed."
3. **RAG-Grounded** — "Responses grounded in lecture slides, transcripts, and FAQs with transparent citations you can verify."

### 4.4 How Iris is Different
Side-by-side comparison section:
- **Left:** Generic chatbot — gives complete solution, no context, student learns nothing
- **Right:** Iris — reads the context, provides a guiding question, student works through the problem
- Inspired by the example in the Koli Calling paper (BWT rotation hint vs. ChatGPT complete solution)

### 4.5 Research Highlights
Stats row, factual:
- **275** students in randomized controlled trial
- **+0.55** Cohen's d increase in intrinsic motivation (Iris vs. No AI)
- **−0.81** Cohen's d reduction in frustration (Iris vs. No AI)
- **3** peer-reviewed publications

Small text linking to the Research section for details.

### 4.6 Student Quotes
Real quotes from the Koli Calling qualitative study:
- "Iris was clearly aware of the context. It pointed me in the right direction. When I asked for getting the strings, it said, you can shift the strings like this for this algorithm without me even mentioning the algorithm." — P19 (Iris)
- Additional quotes as available

### 4.7 Screencast Embed
Placeholder section:
- `[VIDEO PLACEHOLDER — Feature screencast]`
- Guidance text for what to capture (see Section 8)

### 4.8 Audience Quickstart Cards
4 cards linking to the guides:
- **Students** — "Learn how to get the most out of Iris" → Student Guide
- **Instructors** — "Configure Iris for your courses" → Instructor Guide
- **Developers** — "Contribute to Iris" → Developer Guide
- **Administrators** — "Deploy and operate Iris" → Admin Guide

### 4.9 FAQ Section
Expandable accordion:
- "How is Iris different from ChatGPT?" — Scaffolding vs. direct solutions, context-awareness, research-backed design
- "Does Iris give away answers?" — No, 4-tier calibrated hints, self-check mechanism
- "What courses does Iris work with?" — Any course in Artemis, not limited to programming
- "Is Iris free?" — Open source, free for institutions running Artemis
- "How does Iris protect student data?" — Cloud (EU data centers) vs. on-premise options

### 4.10 EduTelligence Ecosystem Footer
Small section showing Iris alongside Artemis, Athena, Memiris, Atlas, Nebula, Logos.

---

## 5. Navigation & Sidebar Structure

### Navbar
`[Iris logo + "Iris"]` | Overview | Student Guide | Instructor Guide | Developer Guide | Admin Guide | Research | `[GitHub icon]`

### Search
`@easyops-cn/docusaurus-search-local` with context filtering:
```typescript
searchContextByPaths: [
  { label: { en: 'Overview' }, path: 'docs/overview' },
  { label: { en: 'Student Guide' }, path: 'docs/student' },
  { label: { en: 'Instructor Guide' }, path: 'docs/instructor' },
  { label: { en: 'Developer Guide' }, path: 'docs/developer' },
  { label: { en: 'Admin Guide' }, path: 'docs/admin' },
  { label: { en: 'Research' }, path: 'docs/research' },
]
```

---

## 6. Documentation Content

### 6.1 Overview Sidebar

**What is Iris?**
- Source: ITiCSE 2024 paper intro, About Iris modal
- Content: What Iris is, why it exists, key differentiators (calibrated scaffolding, context-awareness, RAG grounding)

**Architecture**
- Source: Code exploration
- Content: High-level architecture diagram, pipeline system overview, agent execution flow, RAG pipeline overview
- `[IMAGE PLACEHOLDER: Architecture diagram showing Artemis → Iris → LLM flow]`

**The EduTelligence Ecosystem**
- Source: Artemis intelligence docs
- Content: How Iris fits with Artemis, Athena, Memiris, Atlas, Nebula, Logos. Service status overview.

**Compatibility**
- Source: README compatibility matrix
- Content: Artemis version ↔ Iris version mapping table

### 6.2 Student Guide Sidebar

**Getting Started**
- Source: Artemis branch student docs (iris.mdx)
- Content: AI experience selection (Cloud, On-premise, No AI), finding Iris in Artemis
- `[IMAGE PLACEHOLDER: AI experience selection screen]`

**Course Chat**
- Source: Artemis student docs, C&E:AI paper Section 3
- Content: Asking conceptual questions, how Iris retrieves from lectures/transcripts, citations
- `[IMAGE PLACEHOLDER: Course chat conversation with citation]`

**Exercise Chat**
- Source: Artemis student docs, Koli Calling paper Section 3
- Content: Programming exercise support, automatic context reading, calibrated hints
- `[IMAGE PLACEHOLDER: Exercise chat showing context-aware response]`

**Text Exercise Chat**
- Source: Code exploration (text_exercise_chat_pipeline.py)
- Content: How Iris helps with text-based exercises, scaffolded guidance for writing

**Lecture Chat**
- Source: Code exploration (lecture_chat_pipeline.py)
- Content: Asking about specific lecture content, transcript-based retrieval

**How Iris Helps You Learn**
- Source: Artemis branch student docs, ITiCSE paper Section 3.1
- Content: The 4-tier scaffolding system (subtle hints → guiding questions → conceptual feedback → generalized examples), citations, follow-up suggestions, proactive hints

**Memory**
- Source: Artemis branch student docs, memiris code
- Content: What Iris remembers across sessions, managing/deleting memory data

**Privacy & Data**
- Source: Artemis branch student docs, About Iris modal
- Content: Cloud vs. on-premise data handling, GDPR, what data is sent

**Tips for Effective Use**
- Source: New content based on system understanding
- Content: How to ask good questions, when to use which chat type, what Iris can/can't help with

### 6.3 Instructor Guide Sidebar

**Enabling Iris**
- Source: Artemis instructor docs (course-configuration.mdx)
- Content: Course-level Iris settings, enabling/disabling
- `[IMAGE PLACEHOLDER: Iris course settings panel]`

**Custom Instructions**
- Source: Artemis instructor docs, IrisCourseSettings DTO
- Content: Writing custom instructions for Iris behavior in your course

**Variants**
- Source: Code exploration (variant system), Artemis settings
- Content: Default vs. Advanced variants, when to use each, cost implications

**Rate Limits**
- Source: Artemis config, IrisRateLimitedFeatureInterface
- Content: Setting per-course usage limits, default values

**Lecture Ingestion**
- Source: Artemis instructor docs (lectures.mdx)
- Content: Sending slides and transcriptions to Iris, bulk vs. individual ingestion
- `[IMAGE PLACEHOLDER: Lecture management with Iris ingestion buttons]`

**FAQ Ingestion**
- Source: Code exploration (faq_ingestion_pipeline.py)
- Content: Ingesting course FAQs into Iris's knowledge base

**Tutor Suggestions**
- Source: Artemis instructor docs (communication.mdx)
- Content: AI-powered suggestions for tutors in discussion threads, direct Iris conversations
- `[IMAGE PLACEHOLDER: Tutor suggestion in discussion thread]`

**Pedagogical Approach**
- Source: C&E:AI paper Section 3, ITiCSE paper Section 3
- Content: Why Iris scaffolds instead of solving, the research behind the design, Cognitive Load Theory, Self-Determination Theory

### 6.4 Developer Guide Sidebar

**Local Setup**
- Source: Iris README.MD
- Content: Prerequisites, Poetry install, Docker compose, Weaviate, config files, running locally

**Project Structure**
- Source: Code exploration
- Content: Directory layout with descriptions, key files and their roles

**Pipeline System**
- Source: pipeline.py, abstract_agent_pipeline.py, sub_pipeline.py
- Content: Pipeline base class, PIPELINE_ID, ROLES, VARIANT_DEFS, DEPENDENCIES. How to create a new pipeline. Agent execution flow diagram.

**Variant System**
- Source: Variant class (`iris/domain/variant/variant.py`), pipeline class attrs (VARIANT_DEFS), COURSE_CHAT_PIPELINE_REFACTORING.md (verify still relevant)
- Content: How variants work, model selection, cloud vs. local models, defining new variants

**Tools**
- Source: iris/src/iris/tools/ directory
- Content: The tool system, how agents get grounded, creating new tools, tool schema

**Prompts**
- Source: iris/src/iris/pipeline/prompts/
- Content: Jinja2 templating, prompt design patterns, how context is injected

**RAG Pipeline**
- Source: retrieval/, vector_database/, ingestion/
- Content: Ingestion flow (PDF → chunks → Weaviate), retrieval flow (query rewriting → HyDE → multi-source retrieval → reranking), collection schemas

**Domain Models**
- Source: iris/src/iris/domain/
- Content: DTO hierarchy, data flow between Artemis and Iris, Pydantic models

**Configuration**
- Source: application.example.yml, llm_config.example.yml, config.py
- Content: All configuration options explained, environment variables

**Testing**
- Source: tests/, pyproject.toml test config
- Content: Running tests, test setup, coverage

**Contributing**
- Source: Existing patterns, CLAUDE.local.md
- Content: Code style (pylint, black, isort), PR process, pre-commit hooks

### 6.5 Admin Guide Sidebar

**Deployment**
- Source: README, Docker files
- Content: Docker deployment, production config, resource requirements

**Artemis Integration**
- Source: Artemis application-artemis.yml, admin extension-services docs
- Content: Connecting Iris to Artemis (URL, secret token), health checks, troubleshooting connectivity

**LLM Configuration**
- Source: llm_config.example.yml, llm_manager.py
- Content: Setting up OpenAI, Azure, Ollama, Cohere. Model types (chat, embedding, reranker). Cost tracking.

**Weaviate Setup**
- Source: vector_database/database.py, docker config
- Content: Deploying Weaviate, collection management, backup strategies

**Monitoring**
- Source: sentry.py, langfuse_tracer.py
- Content: Sentry error tracking setup, LangFuse LLM tracing, APScheduler for background jobs

**Troubleshooting**
- Source: README troubleshooting section
- Content: Common issues and solutions

### 6.6 Research Sidebar

**Pedagogical Design**
- Source: C&E:AI paper Section 3
- Content: The 3 architectural pillars — calibrated scaffolding, context-aware agent, RAG grounding. Educational theory foundations (CLT, SDT, ZPD).

**Study Results**
- Source: All 3 papers
- Content: Factual presentation of findings from each study. Key data points, figures described, limitations acknowledged.

**Publications**
- Source: Paper metadata
- Content: Full citations for all 3 papers with DOI links and BibTeX entries:
  1. Bassner, Frankford & Krusche (2024). "Iris: An AI-Driven Virtual Tutor For Computer Science Education." ITiCSE 2024.
  2. Bassner, Lottner & Krusche (2025). "Towards Understanding the Impact of Context-Aware AI Tutors and General-Purpose AI Chatbots on Student Learning." Koli Calling '25.
  3. Bassner, Lenk-Ostendorf, Beinstingel, Wasner & Krusche (2026). "Less stress, better scores, same learning: The dissociation of performance and learning in AI-supported programming education." Computers and Education: AI.

**Citing Iris**
- Content: Recommended citation format, BibTeX entries for copy-paste

---

## 7. Directory Structure

All paths relative to the edutelligence monorepo root (`ls1intum/edutelligence`).

```
iris/docs/
├── docusaurus.config.ts
├── sidebars.ts
├── package.json
├── tsconfig.json
├── babel.config.js
├── src/
│   ├── css/
│   │   └── custom.css
│   ├── pages/
│   │   ├── index.tsx
│   │   └── index.module.css
│   └── components/
│       └── HomepageFeatures/
│           ├── index.tsx
│           └── styles.module.css
├── docs/
│   ├── overview/
│   │   ├── what-is-iris.md
│   │   ├── architecture.md
│   │   ├── ecosystem.md
│   │   └── compatibility.md
│   ├── student/
│   │   ├── getting-started.md
│   │   ├── course-chat.md
│   │   ├── exercise-chat.md
│   │   ├── text-exercise-chat.md
│   │   ├── lecture-chat.md
│   │   ├── how-iris-helps.md
│   │   ├── memory.md
│   │   ├── privacy.md
│   │   └── tips.md
│   ├── instructor/
│   │   ├── enabling-iris.md
│   │   ├── custom-instructions.md
│   │   ├── variants.md
│   │   ├── rate-limits.md
│   │   ├── lecture-ingestion.md
│   │   ├── faq-ingestion.md
│   │   ├── tutor-suggestions.md
│   │   └── pedagogical-approach.md
│   ├── developer/
│   │   ├── local-setup.md
│   │   ├── project-structure.md
│   │   ├── pipeline-system.md
│   │   ├── variant-system.md
│   │   ├── tools.md
│   │   ├── prompts.md
│   │   ├── rag-pipeline.md
│   │   ├── domain-models.md
│   │   ├── configuration.md
│   │   ├── testing.md
│   │   └── contributing.md
│   ├── admin/
│   │   ├── deployment.md
│   │   ├── artemis-integration.md
│   │   ├── llm-configuration.md
│   │   ├── weaviate-setup.md
│   │   ├── monitoring.md
│   │   └── troubleshooting.md
│   └── research/
│       ├── pedagogical-design.md
│       ├── study-results.md
│       ├── publications.md
│       └── citing-iris.md
└── static/
    └── img/
        ├── iris/
        │   ├── iris-logo-small.png
        │   ├── iris-logo-big-right.png
        │   └── iris-logo-big-left.png
        └── screenshots/
            └── .gitkeep
```

---

## 8. Screencast Guidance

### Recommended Content Order
1. **Course Chat** — Student asks a conceptual question about lecture content, Iris retrieves from slides/transcriptions and answers with citations
2. **Follow-up** — Deeper question, Iris pulls from a different lecture source
3. **Text Exercise** — Student working on a text exercise, Iris scaffolds without writing it for them
4. **Programming Exercise** — Student hits a failing test, Iris reads context automatically, provides a calibrated hint
5. **Scaffolding escalation** — Student still stuck, Iris moves up the 4 tiers
6. **Memory** — Iris references something from a prior session
7. **Instructor view** — Quick shot of enabling Iris, setting custom instructions
8. **Close** — Back to the student

### Production Notes
- Use realistic course content, not dummy data
- Show Artemis UI naturally — don't rush through screens
- Target length: 2–3 minutes
- Capture at high resolution for embedding on the landing page

---

## 9. Image Placeholders

Throughout the documentation, image placeholders follow this format:

```
:::info Screenshot Needed
**[Description of what to capture]**
Specific guidance on the scenario to set up in Artemis.
:::
```

### Required Screenshots
1. AI experience selection screen (student getting started)
2. Course chat conversation with citation
3. Exercise chat showing context-aware response to a failing test
4. Lecture chat with transcript-based retrieval
5. Iris course settings panel (instructor)
6. Lecture management with Iris ingestion buttons
7. Tutor suggestion in a discussion thread
8. About Iris modal (the in-app one)

---

## 10. Content Sources Reference

| Source | Location | Used For |
|--------|----------|----------|
| Iris README | `iris/README.MD` | Dev setup, troubleshooting, compatibility |
| Iris refactoring guide | `iris/COURSE_CHAT_PIPELINE_REFACTORING.md` | Variant system docs |
| application.example.yml | `iris/application.example.yml` | Admin config docs |
| llm_config.example.yml | `iris/llm_config.example.yml` | LLM configuration docs |
| Artemis student docs | `origin/feature/iris/improve-about-iris-links:documentation/docs/student/learning-content/iris.mdx` | Student guide |
| Artemis instructor docs | `~/projects/artemis/documentation/docs/instructor/` | Instructor guide (lectures, communication) |
| Artemis admin docs | `~/projects/artemis/documentation/docs/admin/extension-services.mdx` | Admin guide |
| About Iris modal | `origin/feature/iris/improve-about-iris-links:src/main/webapp/app/iris/overview/about-iris-modal/` | Overview, student guide |
| ITiCSE 2024 paper | `3649217.3653543.pdf` | Overview, research, pedagogical approach |
| Koli Calling '25 paper | `3769994.3770025.pdf` | Research, student quotes |
| C&E:AI 2026 paper | `1-s2.0-S2666920X25001778-main.pdf` | Research, landing page stats, pedagogical design |
| Iris source code | `iris/src/iris/` | Developer guide (all pages) |
| OneTutor competitor | Competitor analysis | Landing page structure inspiration (social proof, FAQ, trust signals) |
