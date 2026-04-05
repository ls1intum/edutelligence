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
  const trackRef = useRef<HTMLDivElement>(null);
  const touchStartX = useRef(0);
  const touchDx = useRef(0);
  const isDragging = useRef(false);

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

  // Swipe handling with live drag feedback
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchDx.current = 0;
    isDragging.current = true;
    if (trackRef.current) {
      trackRef.current.style.transition = "none";
    }
  }, []);

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!isDragging.current || !trackRef.current) return;
      touchDx.current = e.touches[0].clientX - touchStartX.current;
      const offset =
        -(active * 100) +
        (touchDx.current / trackRef.current.parentElement!.clientWidth) * 100;
      trackRef.current.style.transform = `translateX(${offset}%)`;
    },
    [active],
  );

  const handleTouchEnd = useCallback(() => {
    isDragging.current = false;
    if (trackRef.current) {
      trackRef.current.style.transition = "";
    }
    const dx = touchDx.current;
    if (Math.abs(dx) > 50) {
      if (dx < 0 && active < slides.length - 1) {
        goTo(active + 1);
        return;
      } else if (dx > 0 && active > 0) {
        goTo(active - 1);
        return;
      }
    }
    // Snap back if no slide change
    if (trackRef.current) {
      trackRef.current.style.transform = `translateX(-${active * 100}%)`;
    }
  }, [active, goTo]);

  useEffect(() => {
    const first = videoRefs.current[0];
    if (first) {
      first.play().catch(() => {});
    }
  }, []);

  // Update track position when active changes (for tab clicks / auto-advance)
  useEffect(() => {
    if (trackRef.current) {
      trackRef.current.style.transition = "";
      trackRef.current.style.transform = `translateX(-${active * 100}%)`;
    }
  }, [active]);

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

        {/* Mobile: current slide label (desktop hidden) */}
        <div className={styles.videoCarouselMobileHeader}>
          <span className={styles.videoCarouselMobileTitle}>
            {slides[active].title}
          </span>
          {statusBadge(slides[active].status)}
        </div>

        {/* Desktop: stacked videos with opacity */}
        <div className={styles.videoCarouselStage}>
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

        {/* Mobile: horizontal sliding track with title + video + caption per slide */}
        <div
          className={styles.videoCarouselTrackWrapper}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <div
            ref={trackRef}
            className={styles.videoCarouselTrack}
            style={{ transform: `translateX(-${active * 100}%)` }}
          >
            {srcs.map((src, i) => (
              <div key={i} className={styles.videoCarouselSlide}>
                <div className={styles.videoCarouselSlideHeader}>
                  <span className={styles.videoCarouselMobileTitle}>
                    {slides[i].title}
                  </span>
                  {statusBadge(slides[i].status)}
                </div>
                <div className={styles.videoCarouselSlideVideoWrap}>
                  <video
                    ref={(el) => {
                      if (window.innerWidth < 768) {
                        videoRefs.current[i] = el;
                      }
                    }}
                    src={src}
                    controls
                    muted
                    playsInline
                    preload={i === 0 ? "auto" : "metadata"}
                    className={styles.videoCarouselSlideVideo}
                    onEnded={() => handleEnded(i)}
                  />
                </div>
                <p className={styles.videoCarouselSlideCaption}>
                  {slides[i].subtitle}
                </p>
              </div>
            ))}
          </div>
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
