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
      "ChatGPT is a general-purpose chatbot that provides direct answers. Iris is purpose-built for education: it uses calibrated scaffolding to guide students toward understanding rather than handing out solutions. It is deeply integrated into Artemis, so it automatically has context about your code, submissions, and course materials. Its pedagogical approach is backed by peer-reviewed research.",
  },
  {
    question: "Is Iris free?",
    answer:
      "Yes. Iris is open source under the MIT license and free for any institution running Artemis. The source code is available on GitHub at github.com/ls1intum/edutelligence.",
  },
  {
    question: "How does Iris protect student data?",
    answer:
      "Institutions can choose between cloud deployment (using EU-based data centers) or fully on-premise deployment where no data ever leaves the institution\u2019s infrastructure. Iris processes only the data needed for the current interaction and does not train on student data.",
  },
  {
    question: "Does Iris give away answers?",
    answer:
      "No. Iris uses a four-tier calibrated hint system that starts with subtle nudges and only escalates to more explicit guidance when needed. A built-in self-check mechanism ensures responses preserve productive struggle rather than short-circuiting learning.",
  },
  {
    question: "What courses does Iris work with?",
    answer:
      "Iris works with any course hosted on Artemis. While it has particularly deep support for programming exercises (reading code, build logs, and test results), it also supports text exercises, modeling exercises, and general course Q&A through its Course Chat feature.",
  },
];

export default function FaqSection(): React.JSX.Element {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const toggle = (index: number) => {
    setOpenIndex(openIndex === index ? null : index);
  };

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>Frequently Asked Questions</h2>
        <div className={styles.faqList}>
          {faqs.map((faq, i) => {
            const panelId = `faq-panel-${i}`;
            const buttonId = `faq-button-${i}`;
            const isOpen = openIndex === i;
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
