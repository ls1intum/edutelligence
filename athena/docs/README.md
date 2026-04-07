# Athena Documentation

We publish the Athena docs with [Docusaurus](https://docusaurus.io/) so contributors can write content in Markdown/MDX. Please capture new features from the user perspective—these pages also serve as the official user manual for instructors and administrators.

If you are new to Markdown, the [Markdown Guide](https://www.markdownguide.org/) is a handy primer.

## Content guidelines

1. **Use realistic data and personas.** Avoid dummy labels like “Foo Module”; explain scenarios that mirror real Athena deployments.
2. **Write for humans first.** Favor plain language, define unavoidable jargon, and keep paragraphs short. Assume many readers are teaching staff rather than engineers.
3. **Lean on visuals.** Screenshots, diagrams, and short clips make workflows easier to follow than long text blocks.
4. **Tell a story.** Order sections the way a user experiences the system: onboarding → setup → advanced features.
5. **Document known pitfalls.** A tiny FAQ or “Gotchas” section per page saves support time.
6. **Keep accessibility in mind.** Provide alt text, meaningful link text, and high-contrast imagery.
7. **Update continuously.** When a feature changes, update its docs in the same pull request.
8. **Encourage feedback.** Link to GitHub Discussions or issues so users can flag unclear sections.

## Hosting & deployment

- **Primary:** Publish the generated `build/` folder to the environment that serves Athena docs (e.g., GitHub Pages or internal infrastructure). Update `docusaurus.config.ts` `url`/`baseUrl` when the canonical domain is known.
- **Previews:** Use `npm run serve` locally or your CI previews (if configured) so reviewers can validate documentation changes before merging.

Document future CI/CD setup here once the pipeline is finalized.

## Installing Docusaurus locally

Docusaurus requires **Node.js 20+**. Install dependencies once:

```bash
cd athena/docs
npm install
```

## Running the dev server

```bash
npm start
```

This launches <http://localhost:3000> with hot reload so you can edit Markdown and immediately preview it.

## Building the docs

Produce an optimized build:

```bash
npm run build
```

Preview the production bundle locally:

```bash
npm run serve
```

## Writing documentation

### Creating a page

Add a `.md` or `.mdx` file beneath `docs/` (or the eventual `user/`, `dev/`, `admin/` structure once introduced). Wire it into `sidebars.ts` so it shows up in navigation.

### Adding images

- Place **page-specific screenshots** in an `images/` folder next to that Markdown file and link via `./images/filename.png`.
- Put **shared assets** (logos, reused diagrams) in `static/img/` and reference them with `/img/...` paths.

### Docusaurus niceties

- Admonitions: `:::tip ... :::` for callouts.
- Tabs, code blocks with language highlighting, and MDX components are all available—see the [Docusaurus docs](https://docusaurus.io/docs).

## Tooling tips

- VS Code Markdown Preview
- LanguageTool or Grammarly extensions for grammar checks
- Docusaurus IntelliJ plugin (if you develop in JetBrains IDEs)

## Useful references

- [Athena repository](https://github.com/ls1intum/edutelligence)
- [Docusaurus Documentation](https://docusaurus.io/docs)
- [Markdown Guide](https://www.markdownguide.org/)

Document bugs or improvement ideas in GitHub issues so the documentation stays actionable and up-to-date.
