import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

/** Inline SVG icons — lightweight, no external deps */
function LightbulbIcon() {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
    </svg>
  );
}

function CodeIcon() {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
      <line x1="12" y1="2" x2="12" y2="22" opacity="0.3" />
    </svg>
  );
}

function ShieldCheckIcon() {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

const features = [
  {
    icon: <LightbulbIcon />,
    title: "Hints, Not Answers",
    description:
      "Guides students through the problem instead of solving it for them.",
  },
  {
    icon: <CodeIcon />,
    title: "Knows Your Course",
    description:
      "Reads your lecture slides, exercises, and student submissions \u2014 no setup needed.",
  },
  {
    icon: <ShieldCheckIcon />,
    title: "Cites Its Sources",
    description:
      "Every answer links back to the exact slide or material, so students can verify it themselves.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function FeatureCards(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Built for How Instructors Teach</h2>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.featureGrid}
      >
        {features.map((f, i) => (
          <div
            key={f.title}
            className={`${styles.featureCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
          >
            <div className={styles.featureCardIcon}>{f.icon}</div>
            <h3 className={styles.featureCardTitle}>{f.title}</h3>
            <p className={styles.featureCardDesc}>{f.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
