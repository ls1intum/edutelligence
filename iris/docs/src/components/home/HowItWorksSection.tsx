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
      "Iris reads every slide and transcript. It learns your terminology, your examples, and the way you teach the material.",
    emoji: "\uD83E\uDDE0",
  },
  {
    number: "3",
    title: "Students Get Real Answers",
    description:
      "When students ask questions, Iris responds using your course content \u2014 with citations back to specific slides.",
    emoji: "\uD83D\uDCAC",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

function FlowConnector(): React.JSX.Element {
  return (
    <svg
      className={styles.howItWorksConnector}
      viewBox="0 0 800 24"
      fill="none"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <line
        x1="130"
        y1="12"
        x2="370"
        y2="12"
        stroke="var(--ifm-color-primary)"
        strokeWidth="2"
        strokeDasharray="6 4"
        strokeOpacity="0.3"
      />
      <polygon
        points="370,7 380,12 370,17"
        fill="var(--ifm-color-primary)"
        fillOpacity="0.3"
      />
      <line
        x1="430"
        y1="12"
        x2="670"
        y2="12"
        stroke="var(--ifm-color-primary)"
        strokeWidth="2"
        strokeDasharray="6 4"
        strokeOpacity="0.3"
      />
      <polygon
        points="670,7 680,12 670,17"
        fill="var(--ifm-color-primary)"
        fillOpacity="0.3"
      />
    </svg>
  );
}

export default function HowItWorksSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section id="how-it-works" className={styles.section}>
      <h2 className={styles.sectionHeading}>How It Works</h2>
      <p className={styles.sectionSubtitle}>
        Three steps. Minutes of setup. Unlimited student support.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.howItWorksGridWrapper}
      >
        <FlowConnector />
        <div className={styles.howItWorksGrid}>
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
      </div>
    </section>
  );
}
