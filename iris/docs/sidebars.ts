import type { SidebarsConfig } from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  overviewSidebar: [
    { type: "doc", id: "overview/what-is-iris", label: "What is Iris?" },
    { type: "doc", id: "overview/architecture", label: "Architecture" },
    { type: "doc", id: "overview/ecosystem", label: "EduTelligence Ecosystem" },
    { type: "doc", id: "overview/compatibility", label: "Compatibility" },
  ],
  studentSidebar: [
    { type: "doc", id: "student/getting-started", label: "Getting Started" },
    { type: "doc", id: "student/course-chat", label: "Course Chat" },
    { type: "doc", id: "student/exercise-chat", label: "Exercise Chat" },
    {
      type: "doc",
      id: "student/text-exercise-chat",
      label: "Text Exercise Chat",
    },
    { type: "doc", id: "student/lecture-chat", label: "Lecture Chat" },
    {
      type: "doc",
      id: "student/how-iris-helps",
      label: "How Iris Helps You Learn",
    },
    { type: "doc", id: "student/memory", label: "Memory" },
    { type: "doc", id: "student/privacy", label: "Privacy & Data" },
    { type: "doc", id: "student/tips", label: "Tips for Effective Use" },
  ],
  instructorSidebar: [
    { type: "doc", id: "instructor/enabling-iris", label: "Enabling Iris" },
    {
      type: "doc",
      id: "instructor/custom-instructions",
      label: "Custom Instructions",
    },
    { type: "doc", id: "instructor/variants", label: "Variants" },
    { type: "doc", id: "instructor/rate-limits", label: "Rate Limits" },
    {
      type: "doc",
      id: "instructor/lecture-ingestion",
      label: "Lecture Ingestion",
    },
    { type: "doc", id: "instructor/faq-ingestion", label: "FAQ Ingestion" },
    {
      type: "doc",
      id: "instructor/tutor-suggestions",
      label: "Tutor Suggestions",
    },
    {
      type: "doc",
      id: "instructor/pedagogical-approach",
      label: "Pedagogical Approach",
    },
  ],
  developerSidebar: [
    { type: "doc", id: "developer/local-setup", label: "Local Setup" },
    {
      type: "doc",
      id: "developer/project-structure",
      label: "Project Structure",
    },
    { type: "doc", id: "developer/pipeline-system", label: "Pipeline System" },
    { type: "doc", id: "developer/variant-system", label: "Variant System" },
    { type: "doc", id: "developer/tools", label: "Tools" },
    { type: "doc", id: "developer/prompts", label: "Prompts" },
    { type: "doc", id: "developer/rag-pipeline", label: "RAG Pipeline" },
    { type: "doc", id: "developer/domain-models", label: "Domain Models" },
    { type: "doc", id: "developer/configuration", label: "Configuration" },
    { type: "doc", id: "developer/testing", label: "Testing" },
    { type: "doc", id: "developer/contributing", label: "Contributing" },
  ],
  adminSidebar: [
    { type: "doc", id: "admin/deployment", label: "Deployment" },
    {
      type: "doc",
      id: "admin/artemis-integration",
      label: "Artemis Integration",
    },
    { type: "doc", id: "admin/llm-configuration", label: "LLM Configuration" },
    { type: "doc", id: "admin/weaviate-setup", label: "Weaviate Setup" },
    { type: "doc", id: "admin/monitoring", label: "Monitoring" },
    { type: "doc", id: "admin/troubleshooting", label: "Troubleshooting" },
  ],
  researchSidebar: [
    {
      type: "doc",
      id: "research/pedagogical-design",
      label: "Pedagogical Design",
    },
    { type: "doc", id: "research/study-results", label: "Study Results" },
    { type: "doc", id: "research/publications", label: "Publications" },
    { type: "doc", id: "research/citing-iris", label: "Citing Iris" },
  ],
};

export default sidebars;
