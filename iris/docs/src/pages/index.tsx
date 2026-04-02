import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import VideoCarousel from "../components/home/VideoCarousel";
import WhyGenericAISection from "../components/home/WhyGenericAISection";
import HowIrisWorksSection from "../components/home/HowIrisWorksSection";
import EvidenceSection from "../components/home/EvidenceSection";
import PrivacySection from "../components/home/PrivacySection";
import StudentQuotes from "../components/home/StudentQuotes";
import AudienceCards from "../components/home/AudienceCards";
import FaqSection from "../components/home/FaqSection";
import ClosingCta from "../components/home/ClosingCta";
import SectionNav from "../components/home/SectionNav";
import styles from "../components/home/styles.module.css";

export default function Home(): React.JSX.Element {
  return (
    <Layout
      title="Iris — The AI Tutor that Teaches"
      description="An AI tutor that teaches, not just answers. Built into Artemis, backed by peer-reviewed research at TU Munich."
    >
      <SectionNav />
      {/* 1. Hero */}
      <HeroSection />

      {/* 2. Trust Bar */}
      <TrustBar />

      {/* 3. Video Carousel */}
      <VideoCarousel />

      {/* 4. Why Generic AI Falls Short */}
      <WhyGenericAISection />

      {/* 5. How Iris Works (no sectionLazy — content-visibility clips the diagonal) */}
      <HowIrisWorksSection />

      {/* 6. Evidence & Scale (no sectionLazy — content-visibility clips the diagonal) */}
      <EvidenceSection />

      {/* 7. Student Perspectives */}
      <div className={styles.sectionLazy}>
        <StudentQuotes />
      </div>

      {/* 10. Privacy & Governance */}
      <div className={styles.sectionLazy}>
        <PrivacySection />
      </div>

      {/* 11. Getting Started */}
      <div className={styles.sectionLazy}>
        <AudienceCards />
      </div>

      {/* 12. Closing CTA */}
      <div className={styles.sectionLazy}>
        <ClosingCta />
      </div>

      {/* 13. FAQ */}
      <div className={styles.sectionLazy}>
        <FaqSection />
      </div>
    </Layout>
  );
}
