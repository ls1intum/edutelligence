import { useEffect, useState } from "react";

import { FullScreen, useFullScreenHandle } from "react-full-screen";

import ExerciseDetail from "@/components/details/exercise_detail";
import ModuleSelectAndConfig from "@/components/selectors/module_and_config_select";
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

  return (
    <FullScreen
      handle={handle}
      className="bg-white rounded-md p-4 mb-8 space-y-2"
    >
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
      </div>
      <div
        className={twMerge(
          "w-full flex gap-4 snap-x snap-mandatory overflow-x-auto",
          handle.active ? "h-[calc(100vh-4.5rem)]" : "h-[calc(100vh-8rem)]"
        )}
        key={experiment.exercise.id}
      >
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto z-20">
          <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
            <h4 className="text-lg font-bold">Exercise Details</h4>
          </div>
          <div className="shrink-0 w-[calc(50vw-2rem)] pr-2">
            <ExerciseDetail
              exercise={experiment.exercise}
              hideDisclosure
              openedInitially
            />
          </div>
        </div>
        <div className="flex flex-col shrink-0 snap-start overflow-y-auto">
          <div className="shrink-0 w-[calc(50vw-2rem)] pr-2">
            <ExperimentSubmissions experiment={experiment} />
          </div>
        </div>

        {moduleConfigurations.map((moduleConfiguration) => (
          <div
            key={moduleConfiguration.id}
            className="flex flex-col shrink-0 snap-start overflow-y-auto"
          >
            <div className="shrink-0 w-[calc(50vw-2rem)] px-2">
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
