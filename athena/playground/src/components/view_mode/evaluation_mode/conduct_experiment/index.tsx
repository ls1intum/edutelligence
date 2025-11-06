import type { ModuleConfiguration } from "../configure_modules";
import type { Experiment } from "../define_experiment";
import type { ExperimentStep } from "@/hooks/batch_module_experiment";
import type { ConductBatchModuleExperimentHandles } from "./batch_module_experiment";

import { useEffect, useRef, useState } from "react";
import { twMerge } from "tailwind-merge";
import { FullScreen, useFullScreenHandle } from "react-full-screen";

import { downloadJSONFiles } from "@/helpers/download";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import ConductBatchModuleExperiment from "./batch_module_experiment";

type ConductExperimentProps = {
  experiment: Experiment;
  moduleConfigurations: ModuleConfiguration[];
};

export default function ConductExperiment({
  experiment,
  moduleConfigurations,
}: ConductExperimentProps) {
  const fullScreenHandle = useFullScreenHandle();

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

  const [didStartExperiment, setDidStartExperiment] = useState(false);
  const [modulesStep, setModulesStep] = useState<ExperimentStep[]>([]);

  const [viewSubmissionIndex, setViewSubmissionIndex] = useState(0);
  const [moduleRenderOrder, setModuleRenderOrder] = useState<number[]>(
    moduleConfigurations.map((_, index) => index)
  );

  const moduleViewRefs = useRef<(ConductBatchModuleExperimentHandles | null)[]>(
    []
  );

  const handleExport = () => {
    downloadJSONFiles(
      moduleViewRefs.current.flatMap((moduleViewRef, index) => {
        if (!moduleViewRef) return [];
        const data = moduleViewRef.exportData();

        let files: { name: string; data: any }[] = [];
        if (data.results.step !== "notStarted") {
          files.push({
            name: `${experiment.exerciseType}_results_${moduleConfigurations[index].name}_${experiment.id}_run-${data.results.runId}`,
            data: data.results,
          });
          if (data.manualRatings) {
            files.push({
              name: `${experiment.exerciseType}_manual_ratings_${moduleConfigurations[index].name}_${experiment.id}_run-${data.manualRatings.runId}`,
              data: data.manualRatings,
            });
          }
          if (data.automaticEvaluation) {
            files.push({
              name: `${experiment.exerciseType}_automatic_evaluation_${moduleConfigurations[index].name}_${experiment.id}_run-${data.automaticEvaluation.runId}`,
              data: data.automaticEvaluation,
            });
          }
        }
        return files;
      })
    );
  };

  const handleImport = (data: any) => {
    if (!data.experimentId) {
      alert("No experiment id found in the data.");
      return;
    }
    if (data.experimentId !== experiment.id) {
      alert("This data is not for this experiment.");
      return;
    }
    if (!data.moduleConfigurationId) {
      alert("No module configuration id found in the data.");
      return;
    }

    const index = moduleConfigurations.findIndex(
      (moduleConfiguration) =>
        moduleConfiguration.id === data.moduleConfigurationId
    );
    if (index === -1) {
      alert(
        `No module configuration found for id: ${data.moduleConfigurationId}`
      );
      return;
    }

    const moduleViewRef = moduleViewRefs.current[index];
    if (!moduleViewRef) {
      alert("Module view not found.");
      return;
    }

    if (!data.type || !["results", "manualRatings", "automaticEvaluation"].includes(data.type)) {
      alert("No correct type found in the data i.e. 'results', 'manualRatings', or 'automaticEvaluation'.");
      return;
    }
    const type = data.type as "results" | "manualRatings" | "automaticEvaluation";

    try {
      moduleViewRef.importData(data);
      alert(`Successfully imported ${type} data for ${moduleConfigurations[index].name}`);
    } catch (error) {
      console.log(error);
      alert(`Failed to import ${type} data for ${moduleConfigurations[index].name}: ${(error as Error).message}`);
    }
  };

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

  useEffect(() => {
    if (!scrollSliderRef.current) return;
    const scroll = scrollSliderRef.current;
    scroll.addEventListener("scroll", checkScroll);
    return () => scroll.removeEventListener("scroll", checkScroll);
  }, [scrollSliderRef]);

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

  return (
    <FullScreen
      handle={fullScreenHandle}
      className="bg-white rounded-md p-4 mb-8 space-y-2"
    >
      {/* Header */}
      <div className="flex justify-between items-center gap-4">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:gap-4">
          <h3 className="text-2xl font-bold">Conduct Experiment</h3>
          <div className="flex flex-row gap-2">
            <button
              disabled={didStartExperiment}
              className="self-start bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
              onClick={() => setDidStartExperiment(true)}
            >
              {didStartExperiment ? (
                <>Experiment&nbsp;Started</>
              ) : (
                <>Start&nbsp;Experiment</>
              )}
            </button>
            <button
              disabled={modulesStep.every((step) => step === "notStarted")}
              className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100 hover:no-underline disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-transparent"
              onClick={handleExport}
            >
              Export
            </button>
            <label className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100 cursor-pointer">
              Import
              <input
                multiple
                className="hidden"
                type="file"
                accept=".json"
                onChange={(e) => {
                  if (!e.target.files) return;

                  // Create an array to hold the parsed JSON data from each file
                  const fileDataArray: any[] = [];
                  let filesProcessed = 0;

                  const files = Array.from(e.target.files);
                  files.forEach((file) => {
                    const reader = new FileReader();
                    reader.onload = (e) => {
                      filesProcessed += 1;
                      if (e.target && typeof e.target.result === "string") {
                        const jsonData = JSON.parse(e.target.result);
                        fileDataArray.push(jsonData);

                        // If all files have been read, sort and import
                        if (filesProcessed === files.length) {
                          // Sort the array by 'type', 'results' first and then 'manualRatings' or 'automaticEvaluation'
                          const sortedData = fileDataArray.sort((a, b) => {
                            if (a.type === "results" && b.type !== "results") {
                              return -1;
                            }
                            if (a.type !== "results" && b.type === "results") {
                              return 1;
                            }
                            return 0;
                          });

                          // Call handleImport for each item in the sorted array
                          sortedData.forEach((data) => handleImport(data));
                        }
                      }
                    };
                    reader.readAsText(file);
                  });

                  // Reset the input value so that the onChange event will fire again if the same file is selected
                  e.target.value = '';
                }}
              />
            </label>
          </div>
        </div>
        <div className="flex flex-col gap-1 xl:flex-row xl:items-center xl:gap-4">
          {/* Submission switcher */}
          <div className="flex gap-2 items-center">
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
                (id: {experiment.evaluationSubmissions[viewSubmissionIndex]?.id}
                )
              </span>
            </div>
          </div>
          {/* View controls */}
          <div className="flex flex-row gap-1 justify-end order-first xl:order-last">
            <button
              className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100"
              onClick={() => {
                if (fullScreenHandle.active) {
                  fullScreenHandle.exit();
                } else {
                  fullScreenHandle.enter();
                }
              }}
            >
              {fullScreenHandle.active ? "Exit Fullscreen" : "Enter Fullscreen"}
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
      </div>
      {/* Scrollable Slider */}
      <div
        className={twMerge(
          "w-full flex gap-4 snap-x snap-mandatory overflow-x-auto",
          fullScreenHandle.active
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
              fullScreenHandle.active
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
              fullScreenHandle.active
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
                  fullScreenHandle.active
                    ? "w-[calc(50vw-1.5rem)]"
                    : "w-[calc(50vw-7.5rem)]"
                )}
              >
                <ConductBatchModuleExperiment
                  ref={(el) => { moduleViewRefs.current[index] = el; }}
                  fullScreenHandle={fullScreenHandle}
                  experiment={experiment}
                  moduleConfiguration={moduleConfiguration}
                  viewSubmission={
                    experiment.evaluationSubmissions[viewSubmissionIndex]
                  }
                  didStartExperiment={didStartExperiment}
                  onChangeStep={(step) =>
                    setModulesStep((prevStep) => {
                      const newStep = [...prevStep];
                      newStep[index] = step;
                      return newStep;
                    })
                  }
                  moduleOrderControl={{
                    isFirstModule: index === 0,
                    isLastModule: index === moduleRenderOrder.length - 1,
                    onClickPrev: () => {
                      setModuleRenderOrder((prevOrder) => {
                        const newOrder = [...prevOrder];
                        const temp = newOrder[index - 1];
                        newOrder[index - 1] = newOrder[index];
                        newOrder[index] = temp;
                        return newOrder;
                      });
                      slide("prev");
                    },
                    onClickNext: () => {
                      setModuleRenderOrder((prevOrder) => {
                        const newOrder = [...prevOrder];
                        const temp = newOrder[index + 1];
                        newOrder[index + 1] = newOrder[index];
                        newOrder[index] = temp;
                        return newOrder;
                      });
                      slide("next");
                    },
                  }}
                />
              </div>
            </div>
          ))}
      </div>
    </FullScreen>
  );
}
