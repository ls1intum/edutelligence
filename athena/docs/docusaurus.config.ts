import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Athena Documentation',
  tagline: 'Automated Assessment and Feedback System',
  favicon: 'img/favicon.ico',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  url: 'https://ls1intum.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/edutelligence/athena/',

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

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl: 'https://github.com/ls1intum/edutelligence/tree/main/athena/docs/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        language: ['en'],
        docsRouteBasePath: ['docs'],
        docsDir: ['docs/user', 'docs/dev', 'docs/admin'],
        indexBlog: false,
        searchContextByPaths: [
          {label: {en: 'User Guide'}, path: 'docs/user'},
          {label: {en: 'Developer Guide'}, path: 'docs/dev'},
          {label: {en: 'Admin Guide'}, path: 'docs/admin'},
        ],
        hideSearchBarWithNoSearchContext: true,
        useAllContextsWithNoSearchContext: false,
        highlightSearchTermsOnTargetPage: true,
        searchResultContextMaxLength: 60,
      },
    ],
  ],

  themeConfig: {
    // Replace with your project's social card
    image: 'img/athena-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Athena',
      logo: {
        alt: 'Athena Logo',
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
          label: 'Developer Guide',
        },
        {
          type: 'docSidebar',
          sidebarId: 'adminSidebar',
          position: 'left',
          label: 'Admin Guide',
        },
        {
          type: 'search',
          position: 'right',
        },
        {
          href: 'https://github.com/ls1intum/edutelligence/tree/main/athena',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'User Guide',
              to: '/docs/user/overview/athena',
            },
            {
              label: 'Developer Guide',
              to: '/docs/dev/setup/install',
            },
            {
              label: 'Admin Guide',
              to: '/docs/admin/administration_of_deployments/configuration',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Discussions',
              href: 'https://github.com/ls1intum/edutelligence/discussions',
            },
          ],
        },
        {
          title: 'Project',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/ls1intum/edutelligence/tree/main/athena',
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
  } satisfies Preset.ThemeConfig,
};

export default config;
