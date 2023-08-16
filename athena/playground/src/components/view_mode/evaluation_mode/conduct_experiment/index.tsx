import { twMerge } from "tailwind-merge";
import type { ModuleConfiguration } from "../configure_modules";
import type { Experiment } from "../define_experiment";

import { useEffect, useRef, useState } from "react";
import { FullScreen, useFullScreenHandle } from "react-full-screen";
import ExerciseDetail from "@/components/details/exercise_detail";
import ConductBatchModuleExperiment from "./batch_module_experiment";
import SubmissionDetail from "@/components/details/submission_detail";

type ConductExperimentProps = {
  experiment: Experiment;
  moduleConfigurations: ModuleConfiguration[];
};

export default function ConductExperiment({
  experiment,
  moduleConfigurations,
}: ConductExperimentProps) {
  const fullscreenHandle = useFullScreenHandle();

  // Prevent user from leaving the page accidentally
  useEffect(() => {
    const handleBeforeunload = (e: any) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeunload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeunload);
    };
  }, []);

  const [viewSubmissionIndex, setViewSubmissionIndex] = useState(0);
  const [moduleRenderOrder, setModuleRenderOrder] = useState<number[]>(
    moduleConfigurations.map((_, index) => index)
  );

  // Slider stuff
  const scrollSliderRef = useRef<HTMLDivElement>(null);
  const [disableSliderBtnPrev, setDisableSliderBtnPrev] = useState(true);
  const [disableSliderBtnNext, setDisableSliderBtnNext] = useState(false);

  const checkScroll = () => {
    if (!scrollSliderRef.current) return;
    const slider = scrollSliderRef.current;
    setDisableSliderBtnPrev(slider.scrollLeft === 0);
    setDisableSliderBtnNext(
      slider.scrollLeft === slider.scrollWidth - slider.clientWidth
    );
  };

  const slide = (direction: "prev" | "next") => {
    if (!scrollSliderRef.current) return;
    const moveAmount = scrollSliderRef.current.clientWidth * 0.4;
    const slider = scrollSliderRef.current;

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
    if (!scrollSliderRef.current) return;
    const scroll = scrollSliderRef.current;
    scroll.addEventListener("scroll", checkScroll);
    return () => scroll.removeEventListener("scroll", checkScroll);
  }, [scrollSliderRef]);

  return (
    <FullScreen
      handle={fullscreenHandle}
      className="bg-white rounded-md p-4 mb-8 space-y-2"
    >
      {/* Header */}
      <div className="flex flex-row justify-between items-center gap-4">
        <h3 className="text-2xl font-bold">Conduct Experiment</h3>
        {/* Submission switcher */}
        <div className="flex gap-2 flex-1 items-center">
          <button
            disabled={viewSubmissionIndex <= 0}
            className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
            onClick={() => setViewSubmissionIndex(viewSubmissionIndex - 1)}
          >
            ←
          </button>
          <button
            disabled={
              !(
                viewSubmissionIndex + 1 <
                experiment.evaluationSubmissions.length
              )
            }
            className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
            onClick={() => {
              setViewSubmissionIndex(viewSubmissionIndex + 1);
            }}
          >
            →
          </button>
          <div className="text-gray-500">
            Submission {viewSubmissionIndex + 1} of{" "}
            {experiment.evaluationSubmissions.length}{" "}
            <span className="text-gray-400 text-sm">
              (id: {experiment.evaluationSubmissions[viewSubmissionIndex]?.id})
            </span>
          </div>
        </div>
        {/* View controls */}
        <div className="flex flex-row gap-2 justify-start">
          <button
            className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100"
            onClick={() => {
              if (fullscreenHandle.active) {
                fullscreenHandle.exit();
              } else {
                fullscreenHandle.enter();
              }
            }}
          >
            {fullscreenHandle.active ? "Exit Fullscreen" : "Enter Fullscreen"}
          </button>
          <button
            onClick={() => slide("prev")}
            disabled={disableSliderBtnPrev}
            className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          >
            Prev
          </button>
          <button
            onClick={() => slide("next")}
            disabled={disableSliderBtnNext}
            className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
      {/* Scrollable Slider */}
      <div
        className={twMerge(
          "w-full flex gap-4 snap-x snap-mandatory overflow-x-auto",
          fullscreenHandle.active
            ? "h-[calc(100vh-4.5rem)]"
            : "h-[calc(100vh-8rem)]"
        )}
        key={experiment.exercise.id}
        ref={scrollSliderRef}
      >
        {/* Exercise Detail Page */}
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto z-20">
          <div
            className={twMerge(
              "shrink-0 pr-2",
              fullscreenHandle.active
                ? "w-[calc(50vw-1.5rem)]"
                : "w-[calc(50vw-7.5rem)]"
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

        {/* Tutor Feedback Page */}
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto z-20">
          <div
            className={twMerge(
              "shrink-0 pr-2",
              fullscreenHandle.active
                ? "w-[calc(50vw-1.5rem)]"
                : "w-[calc(50vw-7.5rem)]"
            )}
          >
            <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
              <h4 className="text-lg font-bold">Tutor Feedback</h4>
            </div>
            <div className="my-2">
              <SubmissionDetail
                identifier={"tutor"}
                submission={
                  experiment.evaluationSubmissions[viewSubmissionIndex]
                }
                feedbacks={experiment.tutorFeedbacks.filter(
                  (feedback) =>
                    feedback.submission_id ===
                    experiment.evaluationSubmissions[viewSubmissionIndex]?.id
                )}
              />
            </div>
          </div>
        </div>

        {/* Module Pages */}
        {moduleRenderOrder
          .map((index) => moduleConfigurations[index])
          .map((moduleConfiguration, index) => (
            <div
              key={moduleConfiguration.id}
              className="flex flex-col shrink-0 snap-start overflow-y-auto z-20"
            >
              <div
                className={twMerge(
                  "shrink-0 pr-2",
                  fullscreenHandle.active
                    ? "w-[calc(50vw-1.5rem)]"
                    : "w-[calc(50vw-7.5rem)]"
                )}
              >
                <ConductBatchModuleExperiment
                  experiment={experiment}
                  moduleConfiguration={moduleConfiguration}
                  viewSubmission={
                    experiment.evaluationSubmissions[viewSubmissionIndex]
                  }
                  controlView={
                    <div className="flex flex-1 justify-end gap-1 mb-1 self-start">
                      <button
                        disabled={index === 0}
                        className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
                        onClick={() => {
                          setModuleRenderOrder((prevOrder) => {
                            const newOrder = [...prevOrder];
                            const temp = newOrder[index - 1];
                            newOrder[index - 1] = newOrder[index];
                            newOrder[index] = temp;
                            return newOrder;
                          });
                          slide("prev");
                        }}
                      >
                        ←
                      </button>
                      <button
                        disabled={index === moduleRenderOrder.length - 1}
                        className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
                        onClick={() => {
                          setModuleRenderOrder((prevOrder) => {
                            const newOrder = [...prevOrder];
                            const temp = newOrder[index + 1];
                            newOrder[index + 1] = newOrder[index];
                            newOrder[index] = temp;
                            return newOrder;
                          });
                          slide("next");
                        }}
                      >
                        →
                      </button>
                    </div>
                  }
                />
              </div>
            </div>
          ))}
      </div>
    </FullScreen>
  );
}
