import React from "react";
import styles from "./styles.module.css";

const features = [
  {
    title: "Calibrated Scaffolding",
    description:
      "Four tiers of support \u2014 from subtle hints to generalized examples \u2014 preserving productive struggle instead of giving away answers.",
  },
  {
    title: "Context-Aware",
    description:
      "Deeply integrated into Artemis. Iris reads your code, build logs, test results, and course materials automatically \u2014 no copy-pasting needed.",
  },
  {
    title: "RAG-Grounded",
    description:
      "Responses grounded in lecture slides, transcripts, and FAQs with transparent citations you can verify.",
  },
];

export default function FeatureCards(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Why Iris?</h2>
      <p className={styles.sectionSubtitle}>
        Purpose-built for education, not adapted from a general-purpose chatbot.
      </p>
      <div className={styles.featureGrid}>
        {features.map((f) => (
          <div key={f.title} className={styles.featureCard}>
            <h3 className={styles.featureCardTitle}>{f.title}</h3>
            <p className={styles.featureCardDesc}>{f.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
