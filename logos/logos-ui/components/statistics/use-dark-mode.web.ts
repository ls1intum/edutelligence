import { useEffect, useState } from "react";

/**
 * Detects dark mode on web by observing the `dark` class on <html>,
 * which is set by GluestackUI / NativeWind.
 */
export function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() => {
    if (typeof document === "undefined") return false;
    return document.documentElement.classList.contains("dark");
  });

  useEffect(() => {
    if (typeof document === "undefined") return;

    const el = document.documentElement;
    const update = () => setIsDark(el.classList.contains("dark"));

    // Observe class changes on <html>
    const observer = new MutationObserver(update);
    observer.observe(el, { attributes: true, attributeFilter: ["class"] });

    // Also listen for system preference changes (for "system" mode)
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);

    return () => {
      observer.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);

  return isDark;
}
