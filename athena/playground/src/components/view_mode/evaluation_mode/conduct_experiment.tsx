import { useEffect, useState } from "react";

import { FullScreen, useFullScreenHandle } from "react-full-screen";

import ExerciseDetail from "@/components/details/exercise_detail";
import ModuleSelectAndConfig from "../module_requests/module_select_and_config";
import { Experiment } from "./define_experiment";
import RunModuleExperiment from "./run_module_experiment";

export default function ConductExperiment({
  experiment,
}: {
  experiment: Experiment;
}) {
  const [numberOfModuleExperiments, setNumberOfModuleExperiments] =
    useState<number>(1);

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

  return (
    <FullScreen handle={handle}>
      <div className="bg-white rounded-md p-4 space-y-2">
        <div className="flex flex-row justify-between items-center">
          <h3 className="text-2xl font-bold">Conduct Experiment</h3>
          <button
            className="rounded-md p-2 mt-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100"
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
          <div className="flex flex-row gap-1 items-center">
            <span className="text-gray-500 text-sm">
              {numberOfModuleExperiments} Module Experiment
              {numberOfModuleExperiments > 1 ? "s" : ""}
            </span>
            <button
              className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
              onClick={() => {
                if (numberOfModuleExperiments <= 1) {
                  return;
                }
                setNumberOfModuleExperiments(numberOfModuleExperiments - 1);
              }}
            >
              -
            </button>
            <button
              className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
              onClick={() => {
                setNumberOfModuleExperiments(numberOfModuleExperiments + 1);
              }}
            >
              +
            </button>
          </div>
        </div>
        <div
          className="w-full flex gap-4 snap-x snap-mandatory overflow-x-auto max-h-[calc(100vh-6rem)]"
          key={experiment.exercise.id}
        >
          <div className="flex flex-col shrink-0 snap-start overflow-y-auto">
            <div className="shrink-0 w-[calc(50vw-2rem)] pr-2">
              <ExerciseDetail
                exercise={experiment.exercise}
                hideDisclosure
                openedInitially
              />
            </div>
          </div>

          {Array.from({ length: numberOfModuleExperiments }).map((_, index) => (
            <div
              key={index}
              className="flex flex-col shrink-0 snap-start overflow-y-auto"
            >
              <div className="shrink-0 w-[calc(50vw-2rem)] px-2">
                <ModuleSelectAndConfig exerciseType={experiment.exercise.type}>
                  <RunModuleExperiment experiment={experiment} />
                </ModuleSelectAndConfig>
              </div>
            </div>
          ))}
        </div>
      </div>
    </FullScreen>
  );
}
