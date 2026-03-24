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

function DocumentStackWatermark(): React.JSX.Element {
  return (
    <svg
      className={styles.courseMaterialWatermark}
      width="280"
      height="320"
      viewBox="0 0 280 320"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="60"
        y="20"
        width="180"
        height="240"
        rx="8"
        transform="rotate(-6 60 20)"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        opacity="0.15"
      />
      <rect
        x="50"
        y="30"
        width="180"
        height="240"
        rx="8"
        transform="rotate(-3 50 30)"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        opacity="0.2"
      />
      <rect
        x="40"
        y="40"
        width="180"
        height="240"
        rx="8"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        opacity="0.25"
      />
    </svg>
  );
}

const materialTypes = [
  "Lecture Slides",
  "Transcripts",
  "FAQs",
  "Exercises",
  "Student Code",
];

export default function HowIrisWorksSection(): React.JSX.Element {
  const [stepsRef, stepsVisible] = useFadeIn();

  return (
    <section id="how-it-works" className={styles.sectionNavy}>
      <div className={styles.sectionNavyInner}>
        <DocumentStackWatermark />

        <h2 className={styles.sectionHeading}>
          Grounded in Your Course. Guided for Your Students.
        </h2>
        <p className={styles.sectionSubtitle}>
          Iris ingests{" "}
          {materialTypes.map((mat, i) => (
            <span key={mat}>
              {i > 0 && i < materialTypes.length - 1 && ", "}
              {i === materialTypes.length - 1 && ", and "}
              <strong>{mat.toLowerCase()}</strong>
            </span>
          ))}{" "}
          &mdash; then provides context-aware hints inside Artemis.
        </p>

        {/* Three-step flow */}
        <div
          ref={stepsRef as React.RefObject<HTMLDivElement>}
          className={styles.howItWorksGridWrapper}
        >
          <FlowConnector />
          <div className={styles.howItWorksGrid}>
            {steps.map((step, i) => (
              <div
                key={step.title}
                className={`${styles.howItWorksCard} ${styles.fadeIn} ${stepsVisible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
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

        {/* Context awareness note */}
        <p className={styles.sectionSubtitle} style={{ marginTop: "3rem" }}>
          Iris maintains context across conversations, adapting its hints based
          on prior interactions and student progress.
        </p>
      </div>
    </section>
  );
}
