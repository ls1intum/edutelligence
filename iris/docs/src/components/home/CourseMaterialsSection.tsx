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
      "Upload your slide decks and video transcripts. Iris indexes the content so it can reference specific slides when students ask questions \u2014 whether that\u2019s a history timeline, a biology diagram, or a legal case study.",
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

export default function CourseMaterialsSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionNavy}>
      <div className={styles.sectionNavyInner}>
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
