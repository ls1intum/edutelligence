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
      "Iris is embedded in your course context and uses a calibrated hint system instead of direct answers. It references your actual lecture slides with citations, and in a controlled trial with 275 students, this approach led to measurably deeper learning and higher motivation.",
  },
  {
    question: "What does it cost?",
    answer:
      "Iris is free and open-source under the MIT license. You deploy it on your own infrastructure. Costs depend on your hosting setup and LLM provider. See our deployment guide for details.",
  },
  {
    question: "How long does setup take?",
    answer:
      "Most instructors get started in under 15 minutes. Upload your lecture slides to Artemis, click ingest, and Iris is ready to help your students.",
  },
  {
    question: "What if Iris gives a wrong answer?",
    answer:
      "Every response includes citation markers linking to specific lecture slides. Students and instructors can verify any answer against the source material. Iris also runs a self-check on every response before sending it, filtering out answers that don\u2019t meet quality standards.",
  },
  {
    question: "Is this just a prototype?",
    answer:
      "No. Iris has been in production since 2023, used by 1,600+ students across multiple semesters, and validated in 3 peer-reviewed studies. It is actively maintained open-source software with continuous development.",
  },
  {
    question: "How does Iris protect student data?",
    answer:
      "Deploy on-premise so no data leaves your infrastructure, or use EU-based cloud hosting. Iris is fully GDPR compliant and never trains on student data. Instructors control exactly what materials Iris has access to.",
  },
  {
    question: "What courses does Iris work with?",
    answer:
      "Any course on Artemis \u2014 from computer science and engineering to biology, mathematics, law, and the humanities. Iris works with programming exercises, lecture Q&A, and any course content you upload.",
  },
  {
    question: "Does Iris give away answers?",
    answer:
      "No. Iris uses a calibrated hint system that starts with Socratic questions and subtle nudges, only escalating to more explicit guidance when the student needs it. This preserves productive struggle \u2014 the kind of effort that builds real understanding.",
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
        <h2 className={styles.sectionHeading}>Common Questions</h2>
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
