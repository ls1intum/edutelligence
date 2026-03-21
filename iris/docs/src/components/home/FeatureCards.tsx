import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const features = [
  {
    title: "Hints, Not Answers",
    description:
      "Guides students through the problem instead of solving it for them.",
  },
  {
    title: "Context-Aware",
    description: "Reads your code, tests, and course materials automatically.",
  },
  {
    title: "Always Accurate",
    description: "Grounded in lecture content with citations you can verify.",
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
