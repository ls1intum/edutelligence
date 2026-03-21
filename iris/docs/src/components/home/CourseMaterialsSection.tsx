import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

function UploadIcon() {
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
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

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
    >
      <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <circle cx="12" cy="9" r="1" fill="currentColor" />
    </svg>
  );
}

function ChatBubbleIcon() {
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
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

const steps = [
  {
    icon: <UploadIcon />,
    number: "1",
    title: "Instructors share course materials",
    description:
      "Lecture slides, transcriptions, exercises, and FAQs are automatically available to Iris through Artemis.",
  },
  {
    icon: <BrainIcon />,
    number: "2",
    title: "Iris learns your course content",
    description:
      "Iris reads and understands your materials so every answer is grounded in what was actually taught.",
  },
  {
    icon: <ChatBubbleIcon />,
    number: "3",
    title: "Students get accurate, sourced answers",
    description:
      "When students ask a question, Iris responds with hints that reference specific slides and lectures.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function CourseMaterialsSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>
          Powered by Your Course Materials
        </h2>
        <p className={styles.sectionSubtitle}>
          Iris doesn&apos;t make things up. It answers based on your actual
          lectures, slides, and exercises &mdash; so students always get
          accurate, course-specific guidance.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.courseMaterialsGrid}
        >
          {steps.map((step, i) => (
            <div
              key={step.title}
              className={`${styles.courseMaterialCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            >
              <div className={styles.courseMaterialNumber}>{step.number}</div>
              <div className={styles.courseMaterialIcon}>{step.icon}</div>
              <h3 className={styles.courseMaterialTitle}>{step.title}</h3>
              <p className={styles.courseMaterialDesc}>{step.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
