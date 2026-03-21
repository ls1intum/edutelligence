import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

function SlidesIcon() {
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
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function FaqIcon() {
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
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function CitationIcon() {
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
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

const cards = [
  {
    icon: <SlidesIcon />,
    title: "Lecture Slides & Transcripts",
    description:
      "Upload your slide decks and video transcripts. Iris learns the content so it can reference specific slides when students ask questions \u2014 whether that\u2019s a history timeline, a biology diagram, or a legal case study.",
  },
  {
    icon: <FaqIcon />,
    title: "Course FAQs",
    description:
      "Add frequently asked questions to your course. Iris draws on these instructor-curated answers first, ensuring students get your preferred explanations \u2014 not something the AI invented.",
  },
  {
    icon: <CitationIcon />,
    title: "Transparent Citations",
    description:
      "Every answer includes numbered citation markers. Students can see exactly which slide, transcript, or FAQ the information came from. No black boxes, no mystery answers.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

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
      {/* Back document — most rotated */}
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
      <line
        x1="90"
        y1="70"
        x2="210"
        y2="62"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.1"
      />
      <line
        x1="90"
        y1="90"
        x2="190"
        y2="83"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.1"
      />

      {/* Middle document */}
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
      <line
        x1="80"
        y1="80"
        x2="200"
        y2="76"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.12"
      />
      <line
        x1="80"
        y1="100"
        x2="180"
        y2="97"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.12"
      />
      <line
        x1="80"
        y1="120"
        x2="195"
        y2="117"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.12"
      />

      {/* Front document */}
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
      <line
        x1="70"
        y1="90"
        x2="190"
        y2="90"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.15"
      />
      <line
        x1="70"
        y1="110"
        x2="170"
        y2="110"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.15"
      />
      <line
        x1="70"
        y1="130"
        x2="185"
        y2="130"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.15"
      />
      <line
        x1="70"
        y1="150"
        x2="160"
        y2="150"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.15"
      />
      {/* Corner fold */}
      <path
        d="M190 40 L220 40 L220 70 Z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
        opacity="0.15"
      />
    </svg>
  );
}

export default function CourseMaterialsSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionNavy}>
      <div className={styles.sectionNavyInner}>
        <DocumentStackWatermark />
        <h2 className={styles.sectionHeading}>
          Powered by Your Course Materials
        </h2>
        <p className={styles.sectionSubtitle}>
          Iris doesn&apos;t make things up. It answers based on your actual
          lecture slides, video transcripts, and course FAQs &mdash; complete
          with citations so students can trace every answer back to the exact
          source.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.courseMaterialsGrid}
        >
          {cards.map((card, i) => (
            <div
              key={card.title}
              className={`${styles.courseMaterialCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            >
              <div className={styles.courseMaterialIcon}>{card.icon}</div>
              <h3 className={styles.courseMaterialTitle}>{card.title}</h3>
              <p className={styles.courseMaterialDesc}>{card.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
