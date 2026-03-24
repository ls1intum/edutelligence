import React, { useState } from "react";
import styles from "./styles.module.css";

interface FaqEntry {
  question: string;
  answer: string;
}

const faqs: FaqEntry[] = [
  {
    question: "How is Iris different from ChatGPT?",
    answer:
      "Iris is integrated into Artemis and grounded in your actual course materials. It guides students with calibrated hints instead of direct answers, and every response cites specific lecture slides. In a controlled study with 275 students, this approach preserved intrinsic motivation while ChatGPT did not.",
  },
  {
    question: "What does it cost?",
    answer:
      "Iris is free and open-source under the MIT license. You deploy it on your own infrastructure. Costs depend on your hosting setup and AI model provider. See our deployment guide for details.",
  },
  {
    question: "How long does setup take?",
    answer:
      "Upload your lecture slides to Artemis, click ingest, and Iris is ready. Most instructors get started in minutes, not hours.",
  },
  {
    question: "What if my university doesn't use Artemis yet?",
    answer:
      "Artemis is open-source and free to deploy. Over 20 universities already run it for programming courses. The Artemis team at TUM supports new adopters with documentation and direct guidance. Iris is part of Artemis — once Artemis is running, enabling Iris takes minutes.",
  },
  {
    question: "What if Iris gives a wrong answer?",
    answer:
      "Every response includes citation markers linking to specific lecture slides. Students and instructors can verify any answer against the source material. Iris also runs a self-check on every response before sending it.",
  },
  {
    question: "How does Iris protect student data?",
    answer:
      "Deploy on-premise so no data leaves your infrastructure, or use EU-based cloud hosting. Iris is GDPR compliant and never trains on student data. Instructors control exactly which materials Iris can access.",
  },
];

export default function FaqSection(): React.JSX.Element {
  const [openIndices, setOpenIndices] = useState<Set<number>>(new Set());

  const toggle = (index: number) => {
    setOpenIndices((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>Questions Academic Teams Ask</h2>
        <div className={styles.faqList}>
          {faqs.map((faq, i) => {
            const panelId = `faq-panel-${i}`;
            const buttonId = `faq-button-${i}`;
            const isOpen = openIndices.has(i);
            return (
              <div key={faq.question} className={styles.faqItem}>
                <button
                  id={buttonId}
                  className={styles.faqQuestion}
                  onClick={() => toggle(i)}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                >
                  {faq.question}
                  <span
                    className={
                      isOpen ? styles.faqChevronOpen : styles.faqChevron
                    }
                    aria-hidden="true"
                  >
                    &#9662;
                  </span>
                </button>
                {isOpen && (
                  <div
                    id={panelId}
                    role="region"
                    aria-labelledby={buttonId}
                    className={styles.faqAnswer}
                  >
                    {faq.answer}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
