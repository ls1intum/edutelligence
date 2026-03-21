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
import ClosingCta from "../components/home/ClosingCta";
export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Iris — The AI Tutor That Teaches"
      description="An AI tutor that teaches, not just answers. Built into Artemis, backed by peer-reviewed research at TU Munich."
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

      {/* 7. Audience Quickstart Cards */}
      <AudienceCards />

      {/* 8. FAQ */}
      <FaqSection />

      {/* 9. Closing CTA — final action before footer */}
      <ClosingCta />
    </Layout>
  );
}
