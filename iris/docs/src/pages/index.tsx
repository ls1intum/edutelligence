import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import FeatureCards from "../components/home/FeatureCards";
import CourseMaterialsSection from "../components/home/CourseMaterialsSection";
import HowItWorksSection from "../components/home/HowItWorksSection";
import ShowcaseSection from "../components/home/ShowcaseSection";
import ComparisonSection from "../components/home/ComparisonSection";
import WhyNotChatGPTSection from "../components/home/WhyNotChatGPTSection";
import ResearchHighlights from "../components/home/ResearchHighlights";
import DisciplinesSection from "../components/home/DisciplinesSection";
import ComfortTrapSection from "../components/home/ComfortTrapSection";
import StudentQuotes from "../components/home/StudentQuotes";
import ScaleSection from "../components/home/ScaleSection";
import PrivacySection from "../components/home/PrivacySection";
import AudienceCards from "../components/home/AudienceCards";
import FaqSection from "../components/home/FaqSection";
import QuizSection from "../components/home/QuizSection";
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

      {/* 6. See Iris in Action */}
      <ShowcaseSection />

      {/* 6.5. Turn Any Lecture into a Quiz */}
      <QuizSection />

      {/* 7. How Iris Is Different (chat comparison) */}
      <ComparisonSection />

      {/* 8. Why Not Just Use a Generic AI Chatbot? */}
      <WhyNotChatGPTSection />

      {/* 9. Research Highlights */}
      <ResearchHighlights />

      {/* 10. Works for Every Course */}
      <DisciplinesSection />

      {/* 11. The Comfort Trap */}
      <ComfortTrapSection />

      {/* 12. Trusted by Educators */}
      <StudentQuotes />

      {/* 13. Built for Scale */}
      <ScaleSection />

      {/* 14. Your Data, Your Control */}
      <PrivacySection />

      {/* 15. Audience Quickstart Cards */}
      <AudienceCards />

      {/* 16. FAQ */}
      <FaqSection />

      {/* 17. Closing CTA */}
      <ClosingCta />
    </Layout>
  );
}
