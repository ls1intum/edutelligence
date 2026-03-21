import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

interface Option {
  label: string;
  text: string;
  correct?: boolean;
}

const question =
  "Which organelle is responsible for producing ATP in eukaryotic cells?";

const options: Option[] = [
  { label: "A", text: "Ribosome" },
  { label: "B", text: "Golgi apparatus" },
  { label: "C", text: "Mitochondria", correct: true },
  { label: "D", text: "Endoplasmic reticulum" },
];

export default function QuizSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Turn Any Lecture into a Quiz</h2>
      <p className={styles.sectionSubtitle}>
        Iris generates practice questions from your course materials &mdash;
        students can self-test with instant feedback and source citations.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.quizPanel} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
      >
        <div className={styles.quizHeader}>
          <span className={styles.quizBadge}>Practice Question</span>
          <span className={styles.quizSource}>
            Cell Biology &mdash; Lecture 3
          </span>
        </div>
        <p className={styles.quizQuestion}>{question}</p>
        <div className={styles.quizOptions} role="list">
          {options.map((opt) => (
            <div
              key={opt.label}
              role="listitem"
              className={`${styles.quizOption} ${opt.correct ? styles.quizOptionCorrect : ""}`}
            >
              <span
                className={`${styles.quizOptionLabel} ${opt.correct ? styles.quizOptionLabelCorrect : ""}`}
              >
                {opt.correct ? (
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-label="Correct answer"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  opt.label
                )}
              </span>
              <span className={styles.quizOptionText}>{opt.text}</span>
            </div>
          ))}
        </div>
        <div className={styles.quizExplanation}>
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className={styles.quizExplanationIcon}
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4M12 8h.01" />
          </svg>
          <span>
            Based on <strong>slide 12</strong> of your Organic Chemistry
            lecture. Mitochondria use oxidative phosphorylation to convert
            nutrients into ATP, the cell's primary energy currency.
          </span>
        </div>
      </div>
    </section>
  );
}
