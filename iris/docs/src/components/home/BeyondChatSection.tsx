import React from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

/* ─── Quiz data ─── */

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

/* ─── IDE code mockup data ─── */

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

/* ─── Component ─── */

export default function BeyondChatSection(): React.JSX.Element {
  const [quizRef, quizVisible] = useFadeIn();
  const [ideRef, ideVisible] = useFadeIn();
  const [searchRef, searchVisible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Beyond Chat Support</h2>
      <p className={styles.sectionSubtitle}>
        The same grounded system that answers questions can also create learning
        activities and meet students where they code.
      </p>

      <div className={styles.beyondGrid}>
        {/* ── Sub-section 1: Quiz Generation ── */}
        <div>
          <h3 className={styles.beyondSubheading}>
            Turn Any Lecture into a Quiz
            <span className={styles.badgeAvailable}>Available</span>
          </h3>
          <p className={styles.beyondSubtext}>
            Iris generates practice questions from your course materials &mdash;
            students can self-test with instant feedback and source citations.
          </p>

          <div
            ref={quizRef as React.RefObject<HTMLDivElement>}
            className={`${styles.quizPanel} ${styles.fadeIn} ${quizVisible ? styles.fadeInVisible : ""}`}
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
                Based on <strong>slide 12</strong> of your Cell Biology lecture.
                Mitochondria use oxidative phosphorylation to convert nutrients
                into ATP, the cell&apos;s primary energy currency.
              </span>
            </div>
          </div>
        </div>

        {/* ── Sub-section 2: IDE Integration ── */}
        <div>
          <h3 className={styles.beyondSubheading}>
            Iris in Your IDE
            <span className={styles.badgeComingSoon}>Coming Soon</span>
          </h3>
          <p className={styles.beyondSubtext}>
            Coming soon &mdash; Iris will integrate directly into VS Code via
            the Artemis Extension, reading uncommitted code, build output, and
            exercise context in the editor.
          </p>

          <div
            ref={ideRef as React.RefObject<HTMLDivElement>}
            className={`${styles.idePanel} ${styles.fadeIn} ${ideVisible ? styles.fadeInVisible : ""}`}
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
                <code className={styles.ideCode} role="presentation">
                  {codeLines.map((line, i) => (
                    <span key={i} className={styles.ideCodeLine}>
                      <span className={styles.ideLineNumber}>{i + 1}</span>
                      <span className={styles.ideLineContent}>
                        {"  ".repeat(line.indent)}
                        {line.tokens.map((tok, j) => (
                          <span
                            key={j}
                            style={{ color: tokenColors[tok.type] }}
                          >
                            {tok.text}
                          </span>
                        ))}
                      </span>
                      {"\n"}
                    </span>
                  ))}
                </code>
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
              <span>Artemis Extension (preview)</span>
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
      </div>

      {/* ── Sub-section 3: Global Search with Iris ── */}
      <div
        ref={searchRef as React.RefObject<HTMLDivElement>}
        className={`${styles.fadeIn} ${searchVisible ? styles.fadeInVisible : ""}`}
        style={{ marginTop: "3rem" }}
      >
        <h3 className={styles.beyondSubheading}>
          Iris-Powered Global Search
          <span className={styles.badgeAvailable}>Available</span>
        </h3>
        <p className={`${styles.beyondSubtext} ${styles.beyondSubtextNarrow}`}>
          Press <strong>Cmd+K</strong> to search across all course materials.
          Iris surfaces relevant lecture slides by content &mdash; with an
          AI-powered answer panel coming soon.
        </p>
        <figure className={styles.screenshotBlock}>
          <img
            src={useBaseUrl("/img/screenshots/global-search-lecture-3.png")}
            alt="Global search modal showing lecture content results for 'deep learning' with slide previews and page numbers"
            className={styles.screenshotImg}
            width={960}
            height={540}
            loading="lazy"
          />
          <figcaption className={styles.screenshotCaption}>
            Global search surfaces lecture content by keyword with slide
            previews
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
