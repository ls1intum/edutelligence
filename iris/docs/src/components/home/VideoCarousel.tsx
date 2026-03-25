import React, { useState, useRef, useCallback } from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

interface VideoSlide {
  title: string;
  subtitle: string;
  status: "available" | "coming-soon";
}

const slides: VideoSlide[] = [
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
  const touchStartX = useRef(0);

  const srcs = [
    useBaseUrl("/videos/lecture-chat.mp4"),
    useBaseUrl("/videos/quiz.mp4"),
    useBaseUrl("/videos/exercise-ide.mp4"),
    useBaseUrl("/videos/global-search.mp4"),
  ];

  const goTo = useCallback((idx: number) => {
    setActive(idx);
  }, []);

  const handleEnded = useCallback(() => {
    setActive((prev) => (prev + 1) % slides.length);
  }, []);

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

        {/* Single video — key forces remount on tab change */}
        <div
          className={styles.videoCarouselStage}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className={styles.videoCarouselPlayer}>
            <video
              key={active}
              src={srcs[active]}
              autoPlay
              muted
              playsInline
              className={styles.videoCarouselVideoSingle}
              onEnded={handleEnded}
            />
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
