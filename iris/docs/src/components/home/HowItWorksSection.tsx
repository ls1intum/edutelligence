import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const steps = [
  {
    number: "1",
    title: "Your instructor enables Iris",
    description:
      "Instructors activate Iris for their course in Artemis with a single click. No setup required from students.",
    emoji: "\u2705",
  },
  {
    number: "2",
    title: "Iris learns from your lectures",
    description:
      "Lecture slides, transcriptions, and exercises are automatically available. Iris understands the context of your course.",
    emoji: "\uD83D\uDCDA",
  },
  {
    number: "3",
    title: "Ask anything about your course",
    description:
      "Open the chat in Artemis and ask Iris a question. Get guided hints that help you understand \u2014 not just copy-paste answers.",
    emoji: "\uD83D\uDCAC",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function HowItWorksSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>How It Works</h2>
      <p className={styles.sectionSubtitle}>
        Getting started with Iris takes less than a minute. Here&apos;s the
        experience from a student&apos;s perspective.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.howItWorksGrid}
      >
        {steps.map((step, i) => (
          <div
            key={step.title}
            className={`${styles.howItWorksCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
          >
            <div className={styles.howItWorksNumber}>{step.number}</div>
            <div className={styles.howItWorksEmoji} aria-hidden="true">
              {step.emoji}
            </div>
            <h3 className={styles.howItWorksTitle}>{step.title}</h3>
            <p className={styles.howItWorksDesc}>{step.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
