import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Atlas',
  tagline: 'Competency Based Learning Management System',
  favicon: 'img/favicon.ico',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  // Support ReadTheDocs canonical URL if available
  // Extract base URL without path (ReadTheDocs includes /en/version/ in the canonical URL)
  url: process.env.READTHEDOCS_CANONICAL_URL
    ? new URL(process.env.READTHEDOCS_CANONICAL_URL).origin
    : 'https://ls1intum.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For ReadTheDocs, extract the path from canonical URL
  baseUrl: process.env.READTHEDOCS_CANONICAL_URL
    ? new URL(process.env.READTHEDOCS_CANONICAL_URL).pathname
    : '/edutelligence/atlas/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'ls1intum', // Usually your GitHub org/user name.
  projectName: 'edutelligence', // Usually your repo name.

  onBrokenLinks: 'throw',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  themes: ['@docusaurus/theme-mermaid'], // This is correct

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/ls1intum/edutelligence/tree/main/atlas/docs/',
          routeBasePath: '/', // Serve docs at the site's root
        },
        blog: false, // Disable blog
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  markdown: {
    mermaid: true,
  },

  themeConfig: {
    // Replace with your project's social card
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Atlas Documentation',
      logo: {
        alt: 'Atlas Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'userSidebar',
          position: 'left',
          label: 'User Guide',
        },
        {
          type: 'docSidebar',
          sidebarId: 'devSidebar',
          position: 'left',
          label: 'Contributor Guide',
        },
        {
          type: 'docSidebar',
          sidebarId: 'adminSidebar',
          position: 'left',
          label: 'Admin Guide',
        },
        {
          href: 'https://github.com/ls1intum/edutelligence',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'User Guide',
              to: '/user',
            },
            {
              label: 'Contributor Guide',
              to: '/dev/development-process',
            },
            {
              label: 'Admin Guide',
              to: '/admin',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/ls1intum/edutelligence',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Technical University of Munich, Applied Education Technologies. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    mermaid: {
      theme: {light: 'default', dark: 'dark'},
    },
  } satisfies Preset.ThemeConfig,
};

export default config;