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
    text: "It\u2019s easy to learn using ChatGPT. But next day I forget because I just learned it from ChatGPT.",
    attribution: "Information Systems Student, TU Munich",
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
                className={`${styles.quoteDot} ${i === current ? styles.quoteDotActive : ""}`}
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
