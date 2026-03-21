import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const steps = [
  {
    number: "1",
    title: "Upload Your Materials",
    description:
      "Add your lecture slides, transcripts, and FAQs to your course in Artemis. Click one button to send them to Iris.",
    emoji: "\u2705",
  },
  {
    number: "2",
    title: "Iris Learns Your Course",
    description:
      "Iris reads and indexes every slide and transcript. It understands your terminology, your examples, and the way you teach the material.",
    emoji: "\uD83E\uDDE0",
  },
  {
    number: "3",
    title: "Students Get Grounded Answers",
    description:
      "When students ask questions, Iris responds using your course content \u2014 with citations back to specific slides. You stay in control of what Iris knows.",
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
        Three steps. Five minutes of setup. Unlimited student support.
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
