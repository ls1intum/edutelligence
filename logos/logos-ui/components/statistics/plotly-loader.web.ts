const PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js";

type PlotlyLike = {
  newPlot: (...args: any[]) => Promise<any>;
  react: (...args: any[]) => Promise<any>;
  relayout: (...args: any[]) => Promise<any>;
  extendTraces: (...args: any[]) => Promise<any>;
  purge: (...args: any[]) => void;
};

declare global {
  interface Window {
    Plotly?: PlotlyLike;
  }
}

let plotlyPromise: Promise<PlotlyLike> | null = null;

export function loadPlotly(): Promise<PlotlyLike> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Plotly can only be loaded in a browser environment."));
  }

  if (window.Plotly) {
    return Promise.resolve(window.Plotly);
  }

  if (!plotlyPromise) {
    plotlyPromise = new Promise<PlotlyLike>((resolve, reject) => {
      const selector = 'script[src="' + PLOTLY_CDN_URL + '"]';
      const existing = document.querySelector(selector) as HTMLScriptElement | null;

      if (existing) {
        existing.addEventListener("load", () => {
          if (window.Plotly) {
            resolve(window.Plotly);
          } else {
            reject(new Error("Plotly script loaded but window.Plotly is undefined."));
          }
        });
        existing.addEventListener("error", () => {
          reject(new Error("Failed to load Plotly script."));
        });
        return;
      }

      const script = document.createElement("script");
      script.src = PLOTLY_CDN_URL;
      script.async = true;
      script.onload = () => {
        if (window.Plotly) {
          resolve(window.Plotly);
        } else {
          reject(new Error("Plotly script loaded but window.Plotly is undefined."));
        }
      };
      script.onerror = () => {
        reject(new Error("Failed to load Plotly script."));
      };
      document.head.appendChild(script);
    });
  }

  return plotlyPromise;
}
