import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

interface ComparisonRow {
  feature: string;
  chatgpt: boolean;
  iris: boolean;
}

const rows: ComparisonRow[] = [
  { feature: "Knows your specific course content", chatgpt: false, iris: true },
  { feature: "Cites lecture slides and materials", chatgpt: false, iris: true },
  {
    feature: "Gives calibrated hints, not full answers",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Integrated into your learning platform",
    chatgpt: false,
    iris: true,
  },
  { feature: "Backed by peer-reviewed research", chatgpt: false, iris: true },
  {
    feature: "Adapts to the exercise you\u2019re working on",
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
        <h2 className={styles.sectionHeading}>Why Not Just Use ChatGPT?</h2>
        <p className={styles.sectionSubtitle}>
          General-purpose AI chatbots are powerful &mdash; but they weren&apos;t
          designed for education. Here&apos;s what makes Iris different.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={`${styles.comparisonTableWrapper} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        >
          <table className={styles.comparisonTable}>
            <thead>
              <tr>
                <th className={styles.comparisonTableFeatureHeader}>Feature</th>
                <th className={styles.comparisonTableHeader}>ChatGPT</th>
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
                      <span className={styles.checkMark} aria-label="Yes">
                        &#10003;
                      </span>
                    ) : (
                      <span className={styles.crossMark} aria-label="No">
                        &#10007;
                      </span>
                    )}
                  </td>
                  <td className={styles.comparisonTableCellIris}>
                    {row.iris ? (
                      <span className={styles.checkMark} aria-label="Yes">
                        &#10003;
                      </span>
                    ) : (
                      <span className={styles.crossMark} aria-label="No">
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
