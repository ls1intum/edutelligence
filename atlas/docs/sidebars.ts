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
  userSidebar: [
    {
      type: 'doc',
      id: 'user/index',
      label: 'User Guide',
    },
  ],

  devSidebar: [
    {
      type: 'doc',
      id: 'dev/index',
      label: 'Developer Guide',
    },
    {
      type: 'category',
      label: 'Development Process',
      items: [
        'dev/development-process/index',
      ],
    },
    {
      type: 'category',
      label: 'System Design',
      items: [
        'dev/system-design/index',
      ],
    },
    {
      type: 'category',
      label: 'Setup',
      items: [
        'dev/setup/index',
      ],
    },
    {
      type: 'category',
      label: 'AtlasML',
      collapsed: false,
      items: [
        'dev/atlasml/index',
        'dev/atlasml/architecture',
        'dev/atlasml/modules',
        'dev/atlasml/rest-api',
        'dev/atlasml/endpoints',
        'dev/atlasml/middleware',
        'dev/atlasml/weaviate',
        'dev/atlasml/ml-pipelines',
        'dev/atlasml/docker-deployment',
        'dev/atlasml/development-workflow',
        'dev/atlasml/testing',
        'dev/atlasml/troubleshooting',
      ],
    },
  ],

  adminSidebar: [
    {
      type: 'doc',
      id: 'admin/index',
      label: 'Admin Guide',
    },
  ],
};

export default sidebars;
