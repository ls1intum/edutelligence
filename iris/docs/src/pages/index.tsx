import React from "react";
import Layout from "@theme/Layout";
import HeroSection from "../components/home/HeroSection";
import TrustBar from "../components/home/TrustBar";
import WhyGenericAISection from "../components/home/WhyGenericAISection";
import HowIrisWorksSection from "../components/home/HowIrisWorksSection";
import ShowcaseSection from "../components/home/ShowcaseSection";
import EvidenceSection from "../components/home/EvidenceSection";
import PrivacySection from "../components/home/PrivacySection";
import BeyondChatSection from "../components/home/BeyondChatSection";
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

      {/* 3. Why Generic AI Falls Short */}
      <WhyGenericAISection />

      {/* 5. How Iris Works (no sectionLazy — content-visibility clips the diagonal) */}
      <HowIrisWorksSection />

      {/* 6. See Iris in Action */}
      <div className={styles.sectionLazy}>
        <ShowcaseSection />
      </div>

      {/* 7. Evidence & Scale (no sectionLazy — content-visibility clips the diagonal) */}
      <EvidenceSection />

      {/* 8. Beyond Chat */}
      <div className={styles.sectionLazy}>
        <BeyondChatSection />
      </div>

      {/* 9. Student Perspectives */}
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

      {/* 12. FAQ */}
      <div className={styles.sectionLazy}>
        <FaqSection />
      </div>

      {/* 13. Closing CTA */}
      <div className={styles.sectionLazy}>
        <ClosingCta />
      </div>
    </Layout>
  );
}
