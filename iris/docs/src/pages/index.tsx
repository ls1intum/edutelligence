import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import FeatureCards from "../components/home/FeatureCards";
import ComparisonSection from "../components/home/ComparisonSection";
import ResearchHighlights from "../components/home/ResearchHighlights";
import StudentQuotes from "../components/home/StudentQuotes";
import AudienceCards from "../components/home/AudienceCards";
import FaqSection from "../components/home/FaqSection";
import EcosystemFooter from "../components/home/EcosystemFooter";
import pageStyles from "./index.module.css";

export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Iris — The AI Tutor That Teaches"
      description="Iris is a context-aware virtual tutor integrated into Artemis. Scaffolded hints, guided learning, and grounded responses — backed by peer-reviewed research."
    >
      {/* 1. Hero */}
      <HeroSection />

      {/* 2. Trust Bar */}
      <TrustBar />

      {/* 3. Feature Cards */}
      <FeatureCards />

      {/* 4. How Iris Is Different */}
      <ComparisonSection />

      {/* 5. Research Highlights */}
      <ResearchHighlights />

      {/* 6. Student Quotes */}
      <StudentQuotes />

      {/* 7. Screencast Placeholder */}
      {/* TODO: Replace with Course Chat demo, then programming exercise screencast */}
      <section className={pageStyles.screencastSection}>
        <div className={pageStyles.screencastPlaceholder}>
          Feature screencast coming soon
        </div>
      </section>

      {/* 8. Audience Quickstart Cards */}
      <AudienceCards />

      {/* 9. FAQ */}
      <FaqSection />

      {/* 10. EduTelligence Ecosystem */}
      <EcosystemFooter />
    </Layout>
  );
}
