import type { SidebarsConfig } from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  userSidebar: [
    { type: "doc", id: "user/getting-started", label: "Getting Started" },
    { type: "doc", id: "user/api-usage", label: "Using the API" },
    { type: "doc", id: "batch-processing", label: "Batch Processing" },
    { type: "doc", id: "passkey-login", label: "Passkey Login" },
  ],
  adminSidebar: [
    { type: "doc", id: "admin/installation", label: "Self-hosted Installation" },
    { type: "doc", id: "deployment", label: "Deployment Environments" },
    { type: "doc", id: "admin/configuration", label: "Configuration" },
    { type: "doc", id: "admin/worker-node", label: "Worker Nodes" },
    { type: "doc", id: "admin/operations", label: "Operations and Troubleshooting" },
  ],
  developerSidebar: [
    { type: "doc", id: "developer/local-setup", label: "Local Development" },
    { type: "doc", id: "context-windows", label: "Context Windows" },
    { type: "doc", id: "developer/architecture", label: "Architecture" },
  ],
};

export default sidebars;
