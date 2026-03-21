import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

interface ComparisonRow {
  feature: string;
  chatgpt: boolean;
  iris: boolean;
}

const rows: ComparisonRow[] = [
  {
    feature: "Knows your specific course content",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Guides with hints instead of giving full answers",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Cites lecture slides and course materials",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Integrated into your learning platform (LMS)",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "GDPR compliant & university-hosted",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Free for students",
    chatgpt: false,
    iris: true,
  },
  { feature: "Available 24/7", chatgpt: true, iris: true },
  { feature: "Supports natural language questions", chatgpt: true, iris: true },
];

export default function WhyNotChatGPTSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>
          Why Not Just Use a Generic AI Chatbot?
        </h2>
        <p className={styles.sectionSubtitle}>
          Your students are already using ChatGPT. But generic AI chatbots give
          direct answers that feel helpful &mdash; while skipping the thinking
          that actually builds understanding. Here&apos;s what Iris does
          differently.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={`${styles.comparisonTableWrapper} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        >
          <table className={styles.comparisonTable}>
            <thead>
              <tr>
                <th className={styles.comparisonTableFeatureHeader}>Feature</th>
                <th className={styles.comparisonTableHeader}>
                  Generic AI Chatbot
                </th>
                <th
                  className={`${styles.comparisonTableHeader} ${styles.comparisonTableHeaderIris}`}
                >
                  Iris
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.feature} className={styles.comparisonTableRow}>
                  <td className={styles.comparisonTableFeature}>
                    {row.feature}
                  </td>
                  <td className={styles.comparisonTableCell}>
                    {row.chatgpt ? (
                      <span
                        className={styles.checkMark}
                        role="img"
                        aria-label="Yes"
                      >
                        &#10003;
                      </span>
                    ) : (
                      <span
                        className={styles.crossMark}
                        role="img"
                        aria-label="No"
                      >
                        &#10007;
                      </span>
                    )}
                  </td>
                  <td className={styles.comparisonTableCellIris}>
                    {row.iris ? (
                      <span
                        className={styles.checkMark}
                        role="img"
                        aria-label="Yes"
                      >
                        &#10003;
                      </span>
                    ) : (
                      <span
                        className={styles.crossMark}
                        role="img"
                        aria-label="No"
                      >
                        &#10007;
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
