# Migration from Sphinx to Docusaurus

This document describes the migration of Atlas documentation from Sphinx to Docusaurus.

## What Was Migrated

### Documentation Content

All documentation content from the old Sphinx-based system has been migrated:

- **User Guide** (`user/user.md` → `docs/user/index.md`)
- **Developer Guide** (`dev/dev.md` → `docs/dev/index.md`)
- **Admin Guide** (`admin/admin.md` → `docs/admin/index.md`)
- **Development Process** (`dev/development-process/development-process.rst` → `docs/dev/development-process/index.md`)
- **System Design** (`dev/system-design/system-design.md` → `docs/dev/system-design/index.md`)
- **Setup Guide** (`dev/setup/setup.md` → `docs/dev/setup/index.md`)

### Assets

- All images from the development process section (process-model.png, feature-proposal-flow.png, uiux_workflow.png)

### Configuration

- Docusaurus configuration with Atlas branding
- Three-section sidebar structure (User, Contributor, Admin guides)
- GitHub integration for "Edit this page" links
- Custom footer with TUM copyright

## What Changed

### Format Changes

1. **RST to Markdown**: The development-process.rst file was converted from reStructuredText to Markdown
2. **Sphinx directives to Docusaurus admonitions**:
   - `.. note::` → `:::note ... :::`
   - Similar conversions for other admonitions

3. **Figure syntax**: Sphinx figures were converted to standard Markdown images
4. **Anchor references**: RST reference syntax was converted to Markdown link format

### Structure Changes

1. Documentation is now served at the root path (`/`) instead of `/docs`
2. Blog functionality is disabled
3. Removed the tutorial/intro pages that came with the Docusaurus template

## CI/CD Changes

A new GitHub Actions workflow has been created at `.github/workflows/atlas_docs_new.yml`:

- Uses Node.js 20 instead of Python 3.10
- Runs `npm ci && npm run build` instead of `pip install && make html`
- Output directory changed from `atlas/docs/_build/html/` to `atlas/docs-new/build/`
- Deployment configuration remains the same (same server, same deployment mechanism)

## Next Steps

### To Complete the Migration

1. **Test the deployment**: After merging, verify that the documentation deploys correctly to docs.atlas.ase.cit.tum.de

2. **Update workflow paths**: Once confirmed working, update `.github/workflows/atlas_docs_new.yml` to:
   - Change `paths` trigger from `atlas/docs-new/**` to `atlas/docs/**`
   - Rename the file to replace the old workflow

3. **Replace old docs**:
   ```bash
   # Backup old docs
   mv atlas/docs atlas/docs-old
   # Rename new docs
   mv atlas/docs-new atlas/docs
   # Delete old workflow
   rm .github/workflows/atlas_docs.yml
   # Rename new workflow
   mv .github/workflows/atlas_docs_new.yml .github/workflows/atlas_docs.yml
   ```

4. **Clean up old Sphinx files**: After confirming everything works, remove:
   - `atlas/docs-old/` (the backed-up Sphinx docs)
   - Python requirements files
   - Sphinx configuration files

### Optional Enhancements

1. **Bibliography Support**: If needed in the future, install `docusaurus-plugin-bibtex` or similar plugin
2. **Search**: Add Algolia DocSearch or local search plugin
3. **Versioning**: Configure Docusaurus versioning if documentation needs to support multiple Atlas versions
4. **Dark Mode Logo**: Add a separate logo for dark mode
5. **Custom CSS**: Enhance styling to match Atlas branding more closely

## Benefits of Docusaurus

1. **Modern React-based UI**: Better user experience with fast navigation
2. **Markdown-based**: Easier to write and maintain than RST
3. **Built-in Search**: Easy to integrate search functionality
4. **Versioning Support**: Built-in documentation versioning
5. **Better Mobile Support**: Responsive design out of the box
6. **Active Development**: Docusaurus is actively maintained by Meta
7. **Rich Ecosystem**: Many plugins and themes available

## Troubleshooting

### Build Fails

If the build fails, check:
- Node.js version (should be 18.0 or higher)
- All internal links use correct paths
- No broken references to removed files

### Deployment Issues

If deployment fails:
- Verify the build output is in `atlas/docs-new/build/` (or `atlas/docs/build/` after renaming)
- Check SSH credentials and server access
- Verify the deployment paths in the workflow match server configuration

### Local Development

To run locally:
```bash
cd atlas/docs-new  # or atlas/docs after migration
npm install
npm start
```

The site will be available at http://localhost:3000

## Resources

- [Docusaurus Documentation](https://docusaurus.io/docs)
- [Markdown Guide](https://www.markdownguide.org/)
- [Migrating from other tools](https://docusaurus.io/docs/migration)
