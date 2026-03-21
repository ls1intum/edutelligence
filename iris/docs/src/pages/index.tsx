import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import FeatureCards from "../components/home/FeatureCards";
import CourseMaterialsSection from "../components/home/CourseMaterialsSection";
import HowItWorksSection from "../components/home/HowItWorksSection";
import ComparisonSection from "../components/home/ComparisonSection";
import ShowcaseSection from "../components/home/ShowcaseSection";
import WhyNotChatGPTSection from "../components/home/WhyNotChatGPTSection";
import ResearchHighlights from "../components/home/ResearchHighlights";
import DisciplinesSection from "../components/home/DisciplinesSection";
import ComfortTrapSection from "../components/home/ComfortTrapSection";
import StudentQuotes from "../components/home/StudentQuotes";
import PrivacySection from "../components/home/PrivacySection";
import AudienceCards from "../components/home/AudienceCards";
import FaqSection from "../components/home/FaqSection";
import ClosingCta from "../components/home/ClosingCta";
export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Iris — The AI Tutor that Teaches"
      description="An AI tutor that teaches, not just answers. Built into Artemis, backed by peer-reviewed research at TU Munich."
    >
      {/* 1. Hero */}
      <HeroSection />

      {/* 2. Trust Bar */}
      <TrustBar />

      {/* 3. Feature Cards — Why Iris? */}
      <FeatureCards />

      {/* 4. Powered by Your Course Materials */}
      <CourseMaterialsSection />

      {/* 5. How It Works */}
      <HowItWorksSection />

      {/* 6. See Iris in Action (multi-turn showcase) */}
      <ShowcaseSection />

      {/* 7. How Iris Is Different (chat comparison) */}
      <ComparisonSection />

      {/* 7. Why Not Just Use a Generic AI Chatbot? (table) */}
      <WhyNotChatGPTSection />

      {/* 8. Research Highlights */}
      <ResearchHighlights />

      {/* 9. Works for Every Course */}
      <DisciplinesSection />

      {/* 10. The Comfort Trap — research insight */}
      <ComfortTrapSection />

      {/* 10. Trusted by Educators */}
      <StudentQuotes />

      {/* 11. Your Data, Your Control */}
      <PrivacySection />

      {/* 12. Audience Quickstart Cards */}
      <AudienceCards />

      {/* 13. FAQ */}
      <FaqSection />

      {/* 14. Closing CTA */}
      <ClosingCta />
    </Layout>
  );
}
