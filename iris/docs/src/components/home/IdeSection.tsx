import React from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const codeLines = [
  {
    indent: 0,
    tokens: [
      { type: "keyword", text: "def " },
      { type: "function", text: "merge_sort" },
      { type: "plain", text: "(" },
      { type: "param", text: "arr" },
      { type: "plain", text: "):" },
    ],
  },
  {
    indent: 1,
    tokens: [
      { type: "keyword", text: "if " },
      { type: "function", text: "len" },
      { type: "plain", text: "(arr) <= " },
      { type: "number", text: "1" },
      { type: "plain", text: ":" },
    ],
  },
  {
    indent: 2,
    tokens: [
      { type: "keyword", text: "return " },
      { type: "plain", text: "arr" },
    ],
  },
  {
    indent: 1,
    tokens: [
      { type: "plain", text: "mid = " },
      { type: "function", text: "len" },
      { type: "plain", text: "(arr) // " },
      { type: "number", text: "2" },
    ],
  },
  {
    indent: 1,
    tokens: [{ type: "plain", text: "left = merge_sort(arr[:mid])" }],
  },
  {
    indent: 1,
    tokens: [{ type: "plain", text: "right = merge_sort(arr[mid:])" }],
  },
  {
    indent: 1,
    tokens: [
      { type: "keyword", text: "return " },
      { type: "plain", text: "merge(left, right)" },
    ],
  },
  { indent: 0, tokens: [] },
  {
    indent: 0,
    tokens: [
      { type: "keyword", text: "def " },
      { type: "function", text: "merge" },
      { type: "plain", text: "(" },
      { type: "param", text: "left" },
      { type: "plain", text: ", " },
      { type: "param", text: "right" },
      { type: "plain", text: "):" },
    ],
  },
  { indent: 1, tokens: [{ type: "plain", text: "result = []" }] },
  {
    indent: 1,
    tokens: [
      { type: "keyword", text: "while " },
      { type: "plain", text: "left " },
      { type: "keyword", text: "and " },
      { type: "plain", text: "right:" },
    ],
  },
  {
    indent: 2,
    tokens: [
      { type: "keyword", text: "if " },
      { type: "plain", text: "left[" },
      { type: "number", text: "0" },
      { type: "plain", text: "] <= right[" },
      { type: "number", text: "0" },
      { type: "plain", text: "]:" },
    ],
  },
  {
    indent: 3,
    tokens: [
      { type: "plain", text: "result.append(left.pop(" },
      { type: "number", text: "0" },
      { type: "plain", text: "))" },
    ],
  },
];

const tokenColors: Record<string, string> = {
  keyword: "#c586c0",
  function: "#dcdcaa",
  param: "#9cdcfe",
  number: "#b5cea8",
  plain: "#d4d4d4",
};

export default function IdeSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <div>
        <h2 className={styles.sectionHeading}>Iris in Your IDE</h2>
        <p className={styles.sectionSubtitle}>
          For programming courses, Iris works right inside VS Code &mdash;
          reading your code, build output, and test results in real-time.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={`${styles.idePanel} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        >
          {/* VS Code window chrome */}
          <div className={styles.ideHeader}>
            <div className={styles.chatMockupDots}>
              <span className={styles.chatMockupDotRed} />
              <span className={styles.chatMockupDotYellow} />
              <span className={styles.chatMockupDotGreen} />
            </div>
            <div className={styles.ideTabs}>
              <span className={styles.ideTabActive}>main.py</span>
              <span className={styles.ideTab}>test_sort.py</span>
            </div>
          </div>

          <div className={styles.ideBody}>
            {/* Code editor pane */}
            <div className={styles.ideCodePane}>
              <pre className={styles.ideCode}>
                {codeLines.map((line, i) => (
                  <div key={i} className={styles.ideCodeLine}>
                    <span className={styles.ideLineNumber}>{i + 1}</span>
                    <span className={styles.ideLineContent}>
                      {"  ".repeat(line.indent)}
                      {line.tokens.map((tok, j) => (
                        <span key={j} style={{ color: tokenColors[tok.type] }}>
                          {tok.text}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </pre>
            </div>

            {/* Iris chat sidebar */}
            <div className={styles.ideChatPane}>
              <div className={styles.ideChatHeader}>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <span>Iris</span>
              </div>
              <div className={styles.ideChatMessages}>
                <div className={styles.ideChatBubbleStudent}>
                  My test for merge sort is failing
                </div>
                <div className={styles.ideChatBubbleIris}>
                  I see you&apos;re comparing arrays by reference on line 23.
                  Try comparing element-by-element. Your instructor&apos;s
                  slides cover this on slide 15.{" "}
                  <span className={styles.chatCitation}>[1]</span>
                </div>
              </div>
            </div>
          </div>

          {/* Status bar */}
          <div className={styles.ideStatusBar}>
            <span>Python 3.11</span>
            <span>Artemis Extension v0.4.0</span>
          </div>
        </div>
        <figure className={styles.screenshotBlock}>
          <img
            src={useBaseUrl("/img/screenshots/iris-exercise-chat.png")}
            alt="Iris exercise chat widget helping a student with the Strategy Pattern exercise in Artemis"
            className={styles.screenshotImg}
            width={960}
            height={540}
            loading="lazy"
          />
          <figcaption className={styles.screenshotCaption}>
            Iris helps a student with the Strategy Pattern exercise in Artemis
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
