import { useEffect, useRef, useState } from "react";

import { FullScreen, useFullScreenHandle } from "react-full-screen";

import ExerciseDetail from "@/components/details/exercise_detail";
import { Experiment } from "./define_experiment";
import RunModuleExperiment from "./run_module_experiment";
import ExperimentSubmissions from "./experiment_submissions";
import type { ModuleConfiguration } from "./configure_modules";
import { ModuleProvider } from "@/hooks/module_context";
import { twMerge } from "tailwind-merge";

type ConductExperimentProps = {
  experiment: Experiment;
  moduleConfigurations: ModuleConfiguration[];
};

export default function ConductExperiment({
  experiment,
  moduleConfigurations,
}: ConductExperimentProps) {
  useEffect(() => {
    const handleBeforeunload = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeunload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeunload);
    };
  }, []);

  const handle = useFullScreenHandle();

  const [disablePrev, setDisablePrev] = useState(true);
  const [disableNext, setDisableNext] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  const checkScroll = () => {
    if (!scrollRef.current) return;
    const slider = scrollRef.current;
    setDisablePrev(slider.scrollLeft === 0);
    setDisableNext(
      slider.scrollLeft === slider.scrollWidth - slider.clientWidth
    );
  };

  const slide = (direction: "prev" | "next") => {
    if (!scrollRef.current) return;
    const moveAmount = scrollRef.current.clientWidth * 0.4;
    const slider = scrollRef.current;

    if (
      direction === "next" &&
      slider.scrollLeft < slider.scrollWidth - slider.clientWidth
    ) {
      slider.scrollBy({ left: moveAmount, behavior: "smooth" });
    } else if (direction === "prev" && slider.scrollLeft > 0) {
      slider.scrollBy({ left: -moveAmount, behavior: "smooth" });
    }
  };

  useEffect(() => {
    if (!scrollRef.current) return;
    const scroll = scrollRef.current;
    scroll.addEventListener("scroll", checkScroll);
    return () => scroll.removeEventListener("scroll", checkScroll);
  }, [scrollRef]);

  return (
    <FullScreen
      handle={handle}
      className="bg-white rounded-md p-4 mb-8 space-y-2"
    >
      <div className="flex flex-row justify-between items-center">
        <h3 className="text-2xl font-bold">Conduct Experiment</h3>
        <div className="flex flex-row gap-2 justify-start">
          <button
            className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100"
            onClick={() => {
              if (handle.active) {
                handle.exit();
              } else {
                handle.enter();
              }
            }}
          >
            {handle.active ? "Exit Fullscreen" : "Enter Fullscreen"}
          </button>
          <button
            onClick={() => slide("prev")}
            disabled={disablePrev}
            className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          >
            Prev
          </button>
          <button
            onClick={() => slide("next")}
            disabled={disableNext}
            className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
      <div
        className={twMerge(
          "w-full flex gap-4 snap-x snap-mandatory overflow-x-auto",
          handle.active ? "h-[calc(100vh-4.5rem)]" : "h-[calc(100vh-8rem)]"
        )}
        key={experiment.exercise.id}
        ref={scrollRef}
      >
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto z-20">
          <div
            className={twMerge(
              "shrink-0 pr-2",
              handle.active ? "w-[calc(50vw-1.5rem)]" : "w-[calc(50vw-7.5rem)]"
            )}
          >
            <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
              <h4 className="text-lg font-bold">Exercise Details</h4>
            </div>
            <ExerciseDetail
              exercise={experiment.exercise}
              hideDisclosure
              openedInitially
            />
          </div>
        </div>
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto">
          <div
            className={twMerge(
              "shrink-0 pr-2",
              handle.active ? "w-[calc(50vw-1.5rem)]" : "w-[calc(50vw-7.5rem)]"
            )}
          >
            <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
              <h4 className="text-lg font-bold">Tutor Feedback</h4>
            </div>
            <ExperimentSubmissions experiment={experiment} />
          </div>
        </div>
        {moduleConfigurations.map((moduleConfiguration) => (
          <div
            key={moduleConfiguration.id}
            className="flex flex-col shrink-0 snap-start overflow-y-auto"
          >
            <div
              className={twMerge(
                "shrink-0 pr-2",
                handle.active
                  ? "w-[calc(50vw-1.5rem)]"
                  : "w-[calc(50vw-7.5rem)]"
              )}
            >
              <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
                <div className="flex items-center gap-2">
                  <h4 className="text-lg font-bold">
                    {moduleConfiguration.name}
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    <span className="rounded-full bg-indigo-500 text-white px-2 py-0.5 text-xs">
                      Module
                    </span>
                  </div>
                </div>
              </div>
              <ModuleProvider
                module={moduleConfiguration.moduleAndConfig.module}
                moduleConfig={moduleConfiguration.moduleAndConfig.moduleConfig}
              >
                <RunModuleExperiment
                  experiment={experiment}
                  moduleConfiguration={moduleConfiguration}
                />
              </ModuleProvider>
            </div>
          </div>
        ))}
      </div>
    </FullScreen>
  );
}
