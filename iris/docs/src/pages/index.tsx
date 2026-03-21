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
import IdeSection from "../components/home/IdeSection";
import MemorySection from "../components/home/MemorySection";
import ClosingCta from "../components/home/ClosingCta";
import styles from "../components/home/styles.module.css";

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

      {/* 3.5. Gets Smarter the More You Use It */}
      <MemorySection />

      {/* 4. Powered by Your Course Materials */}
      <CourseMaterialsSection />

      {/* 5. How It Works — below the fold, lazy-rendered */}
      <div className={styles.sectionLazy}>
        <HowItWorksSection />
      </div>

      {/* 6. See Iris in Action */}
      <div className={styles.sectionLazy}>
        <ShowcaseSection />
      </div>

      {/* 6.5. Turn Any Lecture into a Quiz */}
      <div className={styles.sectionLazy}>
        <QuizSection />
      </div>

      {/* 7. How Iris Is Different (chat comparison) */}
      <div className={styles.sectionLazy}>
        <ComparisonSection />
      </div>

      {/* 8. Why Not Just Use a Generic AI Chatbot? */}
      <div className={styles.sectionLazy}>
        <WhyNotChatGPTSection />
      </div>

      {/* 9. Research Highlights */}
      <div className={styles.sectionLazy}>
        <ResearchHighlights />
      </div>

      {/* 10. Works for Every Course */}
      <div className={styles.sectionLazy}>
        <DisciplinesSection />
      </div>

      {/* 10.5. Iris in Your IDE */}
      <div className={styles.sectionLazy}>
        <IdeSection />
      </div>

      {/* 11. The Comfort Trap */}
      <div className={styles.sectionLazy}>
        <ComfortTrapSection />
      </div>

      {/* 12. Trusted by Educators */}
      <div className={styles.sectionLazy}>
        <StudentQuotes />
      </div>

      {/* 13. Built for Scale */}
      <div className={styles.sectionLazy}>
        <ScaleSection />
      </div>

      {/* 14. Your Data, Your Control */}
      <div className={styles.sectionLazy}>
        <PrivacySection />
      </div>

      {/* 15. Audience Quickstart Cards */}
      <div className={styles.sectionLazy}>
        <AudienceCards />
      </div>

      {/* 16. FAQ */}
      <div className={styles.sectionLazy}>
        <FaqSection />
      </div>

      {/* 17. Closing CTA */}
      <div className={styles.sectionLazy}>
        <ClosingCta />
      </div>
    </Layout>
  );
}
