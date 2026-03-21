import React, { useState } from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const quotes = [
  {
    text: "It pointed me in the right direction without me even mentioning the algorithm.",
    attribution: "Computer Science Student, TU Munich",
  },
  {
    text: "It didn\u2019t want to answer my question \u2014 it wanted me to actually answer it myself.",
    attribution: "Software Engineering Student, TU Munich",
  },
  {
    text: "It\u2019s very easy to learn using ChatGPT. But next day I will forget.",
    attribution: "Information Systems Student, TU Munich",
  },
  {
    text: "My students stopped asking me the same basic questions. Iris handles those now, and I can focus on deeper discussions in office hours.",
    attribution: "Biology Instructor, TU Munich",
  },
  {
    text: "I was skeptical about AI in education, but Iris actually teaches. It doesn\u2019t just hand out solutions \u2014 it makes students think.",
    attribution: "Mathematics Professor, TU Munich",
  },
  {
    text: "As a TA for 400 students, I can\u2019t answer every question at 2 AM. Iris can \u2014 and it gives the same quality hints I would.",
    attribution: "Engineering Teaching Assistant, TU Munich",
  },
];

export default function StudentQuotes(): React.JSX.Element {
  const [current, setCurrent] = useState(0);
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.quoteBlock} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        aria-live="polite"
      >
        <p key={current} className={styles.quoteText}>
          {quotes[current].text}
        </p>
        <p className={styles.quoteAttribution}>
          &mdash; {quotes[current].attribution}
        </p>
        {quotes.length > 1 && (
          <div className={styles.quoteDots}>
            {quotes.map((_, i) => (
              <button
                key={i}
                className={
                  i === current ? styles.quoteDotActive : styles.quoteDot
                }
                onClick={() => setCurrent(i)}
                aria-label={`Show quote ${i + 1}`}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
