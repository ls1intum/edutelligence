import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

function ShieldIcon() {
  return (
    <svg
      width="36"
      height="36"
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

function ServerIcon() {
  return (
    <svg
      width="36"
      height="36"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg
      width="36"
      height="36"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

const cards = [
  {
    icon: <ShieldIcon />,
    title: "Privacy by Design",
    description:
      "Iris minimizes data shared with LLM providers. Only the context needed for a response is sent \u2014 no bulk uploads, no training on your data.",
  },
  {
    icon: <ServerIcon />,
    title: "University-Hosted",
    description:
      "Iris and Artemis run on your institution\u2019s infrastructure. External cloud processing is limited to LLM inference \u2014 or eliminated entirely with local models.",
  },
  {
    icon: <LockIcon />,
    title: "Instructor Control",
    description:
      "Instructors decide what Iris knows. You control which materials are indexed, and students can opt out of AI features entirely.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

function ShieldWatermark(): React.JSX.Element {
  return (
    <svg
      className={styles.privacyWatermark}
      width="240"
      height="280"
      viewBox="0 0 240 280"
      fill="none"
      aria-hidden="true"
    >
      {/* Large shield outline */}
      <path
        d="M120 16L30 56V136C30 200 120 260 120 260C120 260 210 200 210 136V56L120 16Z"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        opacity="0.08"
      />
      {/* Inner shield */}
      <path
        d="M120 44L52 74V130C52 180 120 228 120 228C120 228 188 180 188 130V74L120 44Z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        opacity="0.05"
      />
      {/* Lock body */}
      <rect
        x="92"
        y="120"
        width="56"
        height="44"
        rx="6"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        opacity="0.1"
      />
      {/* Lock shackle */}
      <path
        d="M102 120V106C102 96 110 88 120 88C130 88 138 96 138 106V120"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        opacity="0.1"
      />
      {/* Keyhole */}
      <circle
        cx="120"
        cy="140"
        r="5"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        opacity="0.08"
      />
      <line
        x1="120"
        y1="145"
        x2="120"
        y2="153"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity="0.08"
      />
    </svg>
  );
}

export default function PrivacySection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section id="privacy" className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <ShieldWatermark />
        <h2 className={styles.sectionHeading}>
          Designed for Institutional Trust
        </h2>
        <p className={styles.sectionSubtitle}>
          Governance, transparency, and course control are core product
          requirements &mdash; not afterthoughts.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.privacyGrid}
        >
          {cards.map((card, i) => (
            <div
              key={card.title}
              className={`${styles.privacyCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            >
              <div className={styles.privacyIcon}>{card.icon}</div>
              <h3 className={styles.privacyTitle}>{card.title}</h3>
              <p className={styles.privacyDesc}>{card.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
