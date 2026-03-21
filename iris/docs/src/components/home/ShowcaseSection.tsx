import React from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

interface Turn {
  speaker: "student" | "iris";
  text: React.ReactNode;
}

const conversation: Turn[] = [
  {
    speaker: "student",
    text: "I don\u2019t understand the difference between mitosis and meiosis. Can you just tell me?",
  },
  {
    speaker: "iris",
    text: (
      <>
        Great question! Before I explain, let me check: do you remember how many
        times the cell divides in each process? That\u2019s a key difference.
        Take a look at <strong>slide 14</strong> from your Cell Biology lecture.{" "}
        <span className={styles.chatCitation}>[1]</span>
      </>
    ),
  },
  {
    speaker: "student",
    text: "I think mitosis is one division and meiosis is two?",
  },
  {
    speaker: "iris",
    text: (
      <>
        Exactly right! Now, think about what that means for the resulting cells.
        If a cell with 46 chromosomes goes through one division, how many
        chromosomes do the daughter cells have? Your lecture{" "}
        <strong>slide 16</strong> has a diagram that might help.{" "}
        <span className={styles.chatCitation}>[2]</span>
      </>
    ),
  },
  {
    speaker: "student",
    text: "So mitosis makes identical cells with 46, and meiosis makes 4 cells with 23?",
  },
  {
    speaker: "iris",
    text: (
      <>
        You got it! That\u2019s the fundamental difference \u2014 and it\u2019s
        why meiosis is essential for reproduction while mitosis handles growth
        and repair. Your instructor covered this on <strong>slide 19</strong>.{" "}
        <span className={styles.chatCitation}>[3]</span> Would you like to
        explore why meiosis produces genetic variation?
      </>
    ),
  },
];

export default function ShowcaseSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();
  const irisLogo = useBaseUrl("/img/iris/iris-logo-big-right.png");

  return (
    <section className={styles.sectionAltSpacious}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeadingAccent}>See Iris in Action</h2>
        <p className={styles.sectionSubtitle}>
          Watch how Iris guides a student through a biology concept step by step
          &mdash; no answers given, just the right questions at the right time.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={`${styles.showcasePanel} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        >
          <div className={styles.showcaseHeader}>
            <div className={styles.chatMockupDots}>
              <span className={styles.chatMockupDotRed} />
              <span className={styles.chatMockupDotYellow} />
              <span className={styles.chatMockupDotGreen} />
            </div>
            <span className={styles.chatMockupTitle}>
              Iris Chat &mdash; Cell Biology
            </span>
          </div>
          <div className={styles.showcaseThread}>
            {conversation.map((turn, i) =>
              turn.speaker === "student" ? (
                <div key={i} className={styles.showcaseMessage}>
                  <div className={styles.showcaseAvatarStudent}>S</div>
                  <div>
                    <div className={styles.showcaseMessageName}>Student</div>
                    <div className={styles.showcaseBubbleStudent}>
                      {turn.text}
                    </div>
                  </div>
                </div>
              ) : (
                <div key={i} className={styles.showcaseMessage}>
                  <div className={styles.showcaseAvatarIris}>
                    <img
                      src={irisLogo}
                      alt=""
                      className={styles.chatAvatarImg}
                    />
                  </div>
                  <div>
                    <div className={styles.showcaseMessageNameIris}>Iris</div>
                    <div className={styles.showcaseBubbleIris}>{turn.text}</div>
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
        <p className={styles.showcaseCaption}>
          Same approach, any subject. Iris guides students toward understanding
          through questions grounded in your actual course materials.
        </p>
        <div className={styles.screenshotBlock}>
          <img
            src={useBaseUrl("/img/screenshots/iris-chat-response-hd.png")}
            alt="Iris chat interface showing a detailed AI response in a real course conversation"
            className={styles.screenshotImg}
            loading="lazy"
          />
          <p className={styles.screenshotCaption}>
            Real Iris conversation from a course at TU Munich
          </p>
        </div>
        <blockquote className={styles.endorseQuote}>
          <p className={styles.endorseQuoteText}>
            &ldquo;Iris was clearly aware of the context. It pointed me in the
            right direction.&rdquo;
          </p>
          <cite className={styles.endorseQuoteCite}>
            &mdash; Student P19 (Iris group), Koli Calling 2025
          </cite>
        </blockquote>
      </div>
    </section>
  );
}
