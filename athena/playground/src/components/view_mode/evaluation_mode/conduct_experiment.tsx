import ExerciseDetail from "@/components/details/exercise_detail";
import ModuleSelectAndConfig from "../module_requests/module_select_and_config";
import { Experiment } from "./define_experiment";
import RunModuleExperiment from "./run_module_experiment";
import { useEffect, useRef } from "react";

export default function ConductExperiment({
  experiment,
}: {
  experiment: Experiment;
}) {
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

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <h3 className="text-2xl font-bold">Conduct Experiment</h3>
      <div
        className="w-full flex gap-6 snap-x snap-mandatory overflow-x-auto max-h-[calc(100vh-6rem)]"
        key={experiment.exercise.id}
      >
        <div className="flex flex-col shrink-0 snap-center overflow-y-auto">
          <div className="shrink-0 w-[50vw] pr-2">
            <ExerciseDetail
              exercise={experiment.exercise}
              hideDisclosure
              openedInitially
            />
          </div>
        </div>

        <div className="flex flex-col shrink-0 snap-center overflow-y-auto">
          <div className="shrink-0 w-[50vw] mx-2">
            <ModuleSelectAndConfig exerciseType={experiment.exercise.type}>
              <RunModuleExperiment experiment={experiment} />
            </ModuleSelectAndConfig>
          </div>
        </div>
      </div>
    </div>
  );
}
