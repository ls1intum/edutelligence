import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import FeatureCards from "../components/home/FeatureCards";
import CourseMaterialsSection from "../components/home/CourseMaterialsSection";
import HowItWorksSection from "../components/home/HowItWorksSection";
import ComparisonSection from "../components/home/ComparisonSection";
import WhyNotChatGPTSection from "../components/home/WhyNotChatGPTSection";
import ResearchHighlights from "../components/home/ResearchHighlights";
import StudentQuotes from "../components/home/StudentQuotes";
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

      {/* 3. Feature Cards */}
      <FeatureCards />

      {/* 4. Powered by Your Course Materials */}
      <CourseMaterialsSection />

      {/* 5. How It Works */}
      <HowItWorksSection />

      {/* 6. How Iris Is Different (chat comparison) */}
      <ComparisonSection />

      {/* 7. Why Not Just Use ChatGPT? (table comparison) */}
      <WhyNotChatGPTSection />

      {/* 8. Research Highlights */}
      <ResearchHighlights />

      {/* 9. Testimonials */}
      <StudentQuotes />

      {/* 10. Audience Quickstart Cards */}
      <AudienceCards />

      {/* 11. FAQ */}
      <FaqSection />

      {/* 12. Closing CTA */}
      <ClosingCta />
    </Layout>
  );
}
