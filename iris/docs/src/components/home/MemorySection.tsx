import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const memoryChips = [
  "Prefers visual explanations",
  "Struggled with recursion",
  "Strong in databases",
  "Learns best with examples",
  "Reviewed linked lists twice",
  "Prefers step-by-step",
];

function BrainIcon() {
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
      <path d="M12 2a5 5 0 0 1 4.9 4 4.5 4.5 0 0 1 2.1 4 4 4 0 0 1-1 7.9V18a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4v-.1A4 4 0 0 1 5 10.5a4.5 4.5 0 0 1 2.1-4A5 5 0 0 1 12 2z" />
      <path d="M12 2v20" opacity="0.3" />
    </svg>
  );
}

export default function MemorySection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  // Evenly space chips around a circle
  const radius = 140;
  const chipCount = memoryChips.length;

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>
        Gets Smarter the More You Use It
      </h2>
      <p className={styles.sectionSubtitle}>
        Iris remembers your learning style, past questions, and progress. Unlike
        generic chatbots, every conversation builds on the last.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.memoryOrbit} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        aria-label="Visual showing memory traits orbiting around Iris"
      >
        {/* Central avatar */}
        <div className={styles.memoryCenter}>
          <BrainIcon />
          <span className={styles.memoryCenterLabel}>Iris Memory</span>
        </div>

        {/* Evenly spaced chips in a circle */}
        {memoryChips.map((chip, i) => {
          const angle = (i / chipCount) * 360 - 90; // start from top
          const rad = (angle * Math.PI) / 180;
          const x = Math.cos(rad) * radius;
          const y = Math.sin(rad) * radius;
          return (
            <span
              key={chip}
              className={styles.memoryChip}
              style={{
                transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`,
                animationDelay: `${i * 0.15}s`,
              }}
            >
              {chip}
            </span>
          );
        })}
      </div>
    </section>
  );
}
