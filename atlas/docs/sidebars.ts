import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  devSidebar: [
    {
      type: 'doc',
      id: 'dev/development-process/index',
      label: 'Development Process',
    },
    {
      type: 'doc',
      id: 'dev/system-design',
      label: 'System Design',
    },
    {
      type: 'doc',
      id: 'dev/setup',
      label: 'Setup',
    },
    {
      type: 'doc',
      id: 'dev/testing',
      label: 'Test Guide',
    },
    {
      type: 'category',
      label: 'Code Reference',
      items: [
        'dev/code-reference/modules',
        'dev/code-reference/rest-api',
        'dev/code-reference/endpoints',
        'dev/code-reference/middleware',
        'dev/code-reference/weaviate',
        'dev/code-reference/ml-pipelines',
      ],
    },
    {
      type: 'category',
      label: 'AtlasML Internals',
      items: [
        'dev/atlasml/overview',
        'dev/atlasml/api',
        'dev/atlasml/models',
        'dev/atlasml/settings_auth',
        'dev/atlasml/weaviate',
      ],
    },
  ],

  adminSidebar: [
    {
      type: 'doc',
      id: 'admin/index',
      label: 'Admin Guide',
    },
    {
      type: 'doc',
      id: 'admin/atlasml-installation',
      label: 'Installation',
    },
    {
      type: 'doc',
      id: 'admin/atlasml-configuration',
      label: 'Configuration',
    },
    {
      type: 'doc',
      id: 'admin/atlasml-deployment',
      label: 'Deployment',
    },
    {
      type: 'doc',
      id: 'admin/atlasml-monitoring',
      label: 'Monitoring',
    },
    {
      type: 'doc',
      id: 'admin/atlasml-troubleshooting',
      label: 'Troubleshooting',
    },
  ],
};

export default sidebars;
