# Atlas Documentation

We use [Docusaurus](https://docusaurus.io/) for creating the Atlas documentation using Markdown.
To get started with Markdown, check out the [Markdown Guide](https://www.markdownguide.org/).

Please document the features that you have developed as **extensive as possible** from the user perspective, because the documentation also serves as a **user manual**. This is really important so that users can better understand how to use Atlas.

Creating a user manual for a service such as Atlas can be a bit of a juggling act, especially when it's for students. Here are some best practices that should help:

## Best Practices

1. Atlas documentation must use **realistic examples** and personas and must avoid the use of test data.

2. **Keep it simple and user-friendly**: Remember, you're writing for end-users, not just fellow tech enthusiasts. Use plain language, avoid jargon, and explain technical terms when they can't be avoided.

3. **Use visual aids**: Screenshots, diagrams, and even short video tutorials can be a lot more effective than pages of text. They make it easier for students to understand and follow instructions.

4. **Structure it intuitively**: Organize the content in a logical flow. Start with basic functions before moving to more advanced features. Think about how a student would use the system and structure your documentation accordingly.

5. **Include a searchable FAQ section**: Let's face it, not everyone is going to read the documentation cover-to-cover. A FAQ section for common issues or questions can be a lifesaver.

6. **Apply accessible and inclusive design**: Make sure your documentation is accessible to all students, including those with disabilities. Use clear fonts, alt text for images, and consider a screen-reader-friendly version.

7. **Update regularly**: Atlas evolves, and so should the documentation. Keep it up-to-date with any changes in the system.

8. **Create a feedback loop**: Encourage users to give feedback on the documentation. They might point out confusing sections or missing information that you hadn't considered.

## Documentation Hosting

### Primary: VM Deployment
The Atlas documentation is automatically deployed to **<https://docs.atlas.ase.cit.tum.de>** via GitHub Actions when changes are pushed to the `main` branch. See [.github/workflows/atlas_docs.yml](../../.github/workflows/atlas_docs.yml) for the CI/CD configuration.

### PR Previews: ReadTheDocs
For developer convenience, [Read the Docs](https://readthedocs.org) automatically builds preview deployments for pull requests. This allows reviewers to see documentation changes without running the docs locally. The configuration is in [.readthedocs.yaml](.readthedocs.yaml).

## Installing Docusaurus Locally

Docusaurus requires Node.js version 18.0 or above (which can be checked by running node -v).

Install the dependencies:

```bash
cd atlas/docs
npm install
```

## Running Docusaurus Locally

To start the local development server with live reloading:

```bash
npm start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Building the Documentation

To generate static content into the build directory:

```bash
npm run build
```

This command generates static content that can be served using any static hosting service.

To test the production build locally:

```bash
npm run serve
```

## Writing Documentation

### Creating a New Page

Create a new .md file in the appropriate directory under docs/.

### Adding Images

Place images in the same directory as your markdown file or in the static/img/ directory.

### Using Docusaurus Features

Docusaurus provides special features like admonitions (note, tip, warning, danger blocks).

## Tool Support

A list of useful tools to write documentation:

- Markdown Preview for Visual Studio Code
- LanguageTool for Visual Studio Code: Provides offline grammar checking
- Docusaurus for IntelliJ

## Useful Resources

- [Docusaurus Documentation](https://docusaurus.io/docs)
- [Markdown Guide](https://www.markdownguide.org/)
