import { useEffect, useRef, useState } from "react";

import { FullScreen, useFullScreenHandle } from "react-full-screen";

import ExerciseDetail from "@/components/details/exercise_detail";
import { Experiment } from "./define_experiment";
import RunModuleExperiment from "./run_module_experiment";
import ExperimentSubmissions from "./experiment_submissions";
import type { ModuleConfiguration } from "./configure_modules";
import { ModuleProvider } from "@/hooks/module_context";
import { twMerge } from "tailwind-merge";
import useHealth from "@/hooks/health";
import useRequestSubmissionSelection from "@/hooks/athena/request_submission_selection";
import SubmissionDetail from "@/components/details/submission_detail";
import useFeedbacks from "@/hooks/playground/feedbacks";

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

  const { data: health } = useHealth();
  const handle = useFullScreenHandle();

  // Submission selector module (index 0) selects the submission
  // from `experiment.experimentSubmissions.evaluationSubmissions`
  const [submissionOrderIndicies, setSubmissionOrderIndicies] = useState<
    number[]
  >([]);
  const [currentSubmissionOrderIndex, setCurrentSubmissionOrderIndex] =
    useState<number>(-1);

  const [moduleRenderOrder, setModuleRenderOrder] = useState<number[]>(
    moduleConfigurations.map((_, index) => index)
  );

  // Uses the submission selector module which is provided in the context
  const { mutate: requestSubmissionSelection } =
    useRequestSubmissionSelection();

  const { data: feedbacks, isLoading: isLoadingFeedbacks } = useFeedbacks();

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
      <div className="flex flex-row justify-between items-center gap-4">
        <h3 className="text-2xl font-bold">Conduct Experiment</h3>
        <div className="flex gap-2 flex-1">
          <button
            disabled={currentSubmissionOrderIndex <= 0}
            className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
            onClick={() =>
              setCurrentSubmissionOrderIndex(currentSubmissionOrderIndex - 1)
            }
          >
            ←
          </button>
          <button
            disabled={
              currentSubmissionOrderIndex ===
                experiment.experimentSubmissions.evaluationSubmissions.length -
                  1 ||
              currentSubmissionOrderIndex === submissionOrderIndicies.length
            }
            className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
            onClick={() => {
              if (
                currentSubmissionOrderIndex ===
                submissionOrderIndicies.length - 1
              ) {
                const submissions =
                  experiment.experimentSubmissions.evaluationSubmissions;
                const allIndices = Array.from(
                  { length: submissions.length },
                  (_, index) => index
                );
                const remainingIndicies = allIndices.filter(
                  (index) => !submissionOrderIndicies.includes(index)
                );

                const submissionsToSelectFrom = remainingIndicies.map(
                  (index) => submissions[index]
                );
                requestSubmissionSelection(
                  {
                    exercise: experiment.exercise,
                    submissions: submissionsToSelectFrom,
                  },
                  {
                    onSuccess: (response) => {
                      const submissionId = response.data as number;
                      let submissionIndex = submissions.findIndex(
                        (submission) => submission.id === submissionId
                      );
                      // Pick random submission
                      if (submissionIndex === -1) {
                        const randomIndex = Math.floor(
                          Math.random() * remainingIndicies.length
                        );
                        submissionIndex = remainingIndicies[randomIndex];
                      }
                      setSubmissionOrderIndicies([
                        ...submissionOrderIndicies,
                        submissionIndex,
                      ]);
                      setCurrentSubmissionOrderIndex(
                        currentSubmissionOrderIndex + 1
                      );
                    },
                  }
                );
              } else {
                setCurrentSubmissionOrderIndex(currentSubmissionOrderIndex + 1);
              }
            }}
          >
            →
          </button>
          <div className="flex flex-col">
            <span className="text-gray-500">
              {currentSubmissionOrderIndex < 0
                ? "No submission selected"
                : `Selected: Submission ${
                    currentSubmissionOrderIndex + 1
                  } (id: ${
                    experiment.experimentSubmissions.evaluationSubmissions[
                      submissionOrderIndicies[currentSubmissionOrderIndex]
                    ]?.id
                  })`}
            </span>
            <span className="text-gray-500">
              Progress: ({currentSubmissionOrderIndex + 1} /{" "}
              {experiment.experimentSubmissions.evaluationSubmissions.length})
            </span>
          </div>
        </div>
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
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto z-20">
          <div
            className={twMerge(
              "shrink-0 pr-2",
              handle.active ? "w-[calc(50vw-1.5rem)]" : "w-[calc(50vw-7.5rem)]"
            )}
          >
            <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
              <h4 className="text-lg font-bold">Tutor Feedback</h4>
            </div>
            <div className="p-4">
            {currentSubmissionOrderIndex >= 0 ? (
              <SubmissionDetail
                identifier={"tutor"}
                submission={experiment.experimentSubmissions.evaluationSubmissions[
                  submissionOrderIndicies[currentSubmissionOrderIndex]
                ]}
                feedbacks={feedbacks?.filter(
                  (feedback) =>
                    feedback.submission_id ===
                    experiment.experimentSubmissions.evaluationSubmissions[
                      submissionOrderIndicies[currentSubmissionOrderIndex]
                    ]?.id
                )}
              />
            ) : (
              <p className="text-gray-500">
                No submission selected. Please click next to select a
                submission.
              </p>
            )}
            </div>
          </div>
        </div>
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
                      {moduleConfigurations[0].id ===
                        moduleConfiguration.id && (
                        <span className="rounded-full bg-indigo-500 text-white px-2 py-0.5 text-xs">
                          Submission Selector
                        </span>
                      )}
                      {health?.modules[
                        moduleConfiguration.moduleAndConfig.module.name
                      ] ? (
                        <span className="rounded-full bg-green-500 text-white px-2 py-0.5 text-xs">
                          Healthy
                        </span>
                      ) : (
                        <span className="rounded-full bg-red-500 text-white px-2 py-0.5 text-xs">
                          Unhealthy
                        </span>
                      )}
                    </div>
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
                  </div>
                </div>
                <ModuleProvider
                  module={moduleConfiguration.moduleAndConfig.module}
                  moduleConfig={
                    moduleConfiguration.moduleAndConfig.moduleConfig
                  }
                >
                  <RunModuleExperiment
                    experiment={experiment}
                    currentSubmissionIndex={
                      currentSubmissionOrderIndex < 0
                        ? -1
                        : submissionOrderIndicies[currentSubmissionOrderIndex]
                    }
                  />
                </ModuleProvider>
              </div>
            </div>
          ))}
      </div>
    </FullScreen>
  );
}
