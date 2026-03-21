import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const features = [
  {
    title: "Hints, Not Answers",
    description:
      "Four tiers of support \u2014 from subtle hints to generalized examples \u2014 preserving productive struggle instead of giving away answers.",
  },
  {
    title: "Context-Aware",
    description:
      "Deeply integrated into Artemis. Iris reads your code, build logs, test results, and course materials automatically \u2014 no copy-pasting needed.",
  },
  {
    title: "Always Accurate",
    description:
      "Responses grounded in lecture slides, transcripts, and FAQs with transparent citations you can verify.",
  },
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function FeatureCards(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Why Iris?</h2>
      <p className={styles.sectionSubtitle}>
        Purpose-built for education, not adapted from a general-purpose chatbot.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.featureGrid}
      >
        {features.map((f, i) => (
          <div
            key={f.title}
            className={`${styles.featureCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
          >
            <h3 className={styles.featureCardTitle}>{f.title}</h3>
            <p className={styles.featureCardDesc}>{f.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
