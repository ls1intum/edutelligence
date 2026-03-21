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
    >
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

const cards = [
  {
    icon: <ShieldIcon />,
    title: "GDPR Compliant",
    description:
      "Iris is built and hosted within the European Union, fully compliant with GDPR and university data protection policies.",
  },
  {
    icon: <ServerIcon />,
    title: "University-Hosted",
    description:
      "Your data stays on your institution\u2019s infrastructure. No student conversations are sent to third-party servers.",
  },
  {
    icon: <LockIcon />,
    title: "Instructor Control",
    description:
      "Instructors decide what Iris knows. You control which materials are shared, and you can review every conversation.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function PrivacySection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Your Data, Your Control</h2>
      <p className={styles.sectionSubtitle}>
        Privacy isn&apos;t an afterthought. Iris is designed from the ground up
        to keep student data safe and give instructors full control.
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
    </section>
  );
}
