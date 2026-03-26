import React, { useState, useRef, useEffect, useCallback } from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

interface VideoSlide {
  src: string;
  title: string;
  subtitle: string;
  status: "available" | "coming-soon";
}

const slides: Omit<VideoSlide, "src">[] = [
  {
    title: "Lecture Chat",
    subtitle:
      "Ask anything about a lecture. Iris searches your course materials, cites exact sources, and lets you jump straight to the relevant page.",
    status: "available",
  },
  {
    title: "Quiz Generation",
    subtitle:
      "Challenge yourself on any topic. Iris creates questions from your course content and explains every answer with direct source links.",
    status: "coming-soon",
  },
  {
    title: "Exercise Support",
    subtitle:
      "Get guided help on assignments — in the browser or your local IDE. Iris sees your code, your progress, and nudges you toward the solution without giving it away.",
    status: "available",
  },
  {
    title: "Global Search",
    subtitle:
      "Search across all course materials and get an AI-powered summary of the most relevant results — right from the search bar.",
    status: "coming-soon",
  },
];

export default function VideoCarousel(): React.JSX.Element {
  const [active, setActive] = useState(0);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);
  const touchStartX = useRef(0);

  const lectureSrc = useBaseUrl("/videos/lecture-chat.mp4");
  const quizSrc = useBaseUrl("/videos/quiz.mp4");
  const exerciseSrc = useBaseUrl("/videos/exercise-ide.mp4");
  const searchSrc = useBaseUrl("/videos/global-search.mp4");

  const srcs = [lectureSrc, quizSrc, exerciseSrc, searchSrc];

  const goTo = useCallback((idx: number) => {
    setActive(idx);
    videoRefs.current.forEach((v, i) => {
      if (!v) return;
      if (i === idx) {
        v.currentTime = 0;
        v.play().catch(() => {});
      } else {
        v.pause();
      }
    });
  }, []);

  const handleEnded = useCallback(
    (idx: number) => {
      goTo((idx + 1) % slides.length);
    },
    [goTo],
  );

  // Swipe handling
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 50) {
        if (dx < 0 && active < slides.length - 1) {
          goTo(active + 1);
        } else if (dx > 0 && active > 0) {
          goTo(active - 1);
        }
      }
    },
    [active, goTo],
  );

  useEffect(() => {
    const first = videoRefs.current[0];
    if (first) {
      first.play().catch(() => {});
    }
  }, []);

  const statusBadge = (status: "available" | "coming-soon") => (
    <span
      className={
        status === "available"
          ? styles.badgeAvailableSmall
          : styles.badgeComingSoonSmall
      }
    >
      {status === "available" ? "Available" : "Coming Soon"}
    </span>
  );

  return (
    <section className={styles.videoCarouselSection}>
      <div className={styles.videoCarouselInner}>
        <h2 className={styles.sectionHeadingAccent}>See Iris in Action</h2>
        <p className={styles.sectionSubtitle}>
          Four ways Iris supports students &mdash; from lecture Q&amp;A to
          coding exercises and smart search.
        </p>

        {/* Desktop: tab bar */}
        <div className={styles.videoCarouselTabs} role="tablist">
          {slides.map((slide, i) => (
            <button
              key={i}
              role="tab"
              aria-selected={i === active}
              className={`${styles.videoCarouselTab} ${i === active ? styles.videoCarouselTabActive : ""}`}
              onClick={() => goTo(i)}
            >
              <span className={styles.videoCarouselTabTitle}>
                {slide.title}
              </span>
              {statusBadge(slide.status)}
            </button>
          ))}
        </div>

        {/* Mobile: current slide label + swipe hint */}
        <div className={styles.videoCarouselMobileHeader}>
          <span className={styles.videoCarouselMobileTitle}>
            {slides[active].title}
          </span>
          {statusBadge(slides[active].status)}
          {active < slides.length - 1 && (
            <span className={styles.videoCarouselSwipeHint}>
              Swipe for next &rarr;
            </span>
          )}
        </div>

        {/* Video + description */}
        <div
          className={styles.videoCarouselStage}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className={styles.videoCarouselPlayer}>
            {srcs.map((src, i) => (
              <video
                key={i}
                ref={(el) => {
                  videoRefs.current[i] = el;
                }}
                src={src}
                controls
                muted
                playsInline
                preload={i === 0 ? "auto" : "metadata"}
                className={`${styles.videoCarouselVideo} ${i === active ? styles.videoCarouselVideoActive : ""}`}
                onEnded={() => handleEnded(i)}
              />
            ))}
          </div>
          <p className={styles.videoCarouselCaption}>
            {slides[active].subtitle}
          </p>
        </div>

        {/* Dot indicators */}
        <div className={styles.videoCarouselDots}>
          {slides.map((_, i) => (
            <button
              key={i}
              aria-label={`Go to video ${i + 1}`}
              className={`${styles.videoCarouselDot} ${i === active ? styles.videoCarouselDotActive : ""}`}
              onClick={() => goTo(i)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
