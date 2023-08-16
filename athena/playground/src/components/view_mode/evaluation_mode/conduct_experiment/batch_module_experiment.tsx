import { ModuleProvider } from "@/hooks/module_context";
import { ModuleConfiguration } from "../configure_modules";
import { Experiment } from "../define_experiment";
import useBatchModuleExperiment from "@/hooks/batch_module_experiment";
import ModuleExperimentProgress from "./module_experiment_progress";
import type { Submission } from "@/model/submission";
import SubmissionDetail from "@/components/details/submission_detail";
import { useEffect, useState } from "react";
import useHealth from "@/hooks/health";
import { twMerge } from "tailwind-merge";

type ConductBatchModuleExperimentProps = {
  experiment: Experiment;
  moduleConfiguration: ModuleConfiguration;
  viewSubmission: Submission;
};

function ConductBatchModuleExperiment({
  experiment,
  moduleConfiguration,
  viewSubmission,
}: ConductBatchModuleExperimentProps) {
  const { data: health } = useHealth();
  const moduleExperiment = useBatchModuleExperiment(experiment);

  const [showProgress, setShowProgress] = useState(true);

  useEffect(() => {
    console.log(
      `Feedbacks: ${
        moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
          viewSubmission.id
        )?.suggestions.length
      }`,
      moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
        viewSubmission.id
      )?.suggestions
    );
    console.log(moduleExperiment.data.submissionsWithFeedbackSuggestions);
  }, [moduleExperiment.data.submissionsWithFeedbackSuggestions]);

  return (
    <div>
      <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
        <div className="flex items-center gap-2">
          <h4 className="text-lg font-bold">{moduleConfiguration.name}</h4>
          <div className="flex flex-wrap gap-1">
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
          <div className="flex flex-1 justify-end gap-2 mb-1 items-center">
            <button
              className={twMerge("text-gray-500")}
              onClick={() => {
                setShowProgress((prev) => !prev);
              }}
            >
              {showProgress ? "Hide" : "Show"} Progress
              <span
                className="inline-block transform transition-transform duration-200 ml-1"
                style={{
                  transform: showProgress ? "rotate(90deg)" : "rotate(0deg)",
                }}
              >
                ▶
              </span>
            </button>
            {moduleExperiment.data.step === "finished" && (
              <span className="rounded-full bg-green-500 text-white px-2 py-0.5 text-xs">
                Finished
              </span>
            )}
            {moduleExperiment.data.step !== "finished" && (
              <span className="rounded-full bg-yellow-500 text-white px-2 py-0.5 text-xs">
                In Progress
              </span>
            )}
          </div>
        </div>
        {showProgress && (
          <div className="my-2">
            <ModuleExperimentProgress
              experiment={experiment}
              moduleExperiment={moduleExperiment}
            />
          </div>
        )}
      </div>
      <div className="my-2 space-y-2">
        {moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
          viewSubmission.id
        ) === undefined && (
          <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 text-sm text-yellow-700 flex flex-col gap-1">
            <span className="font-bold">No feedbacks yet</span>
            <span className="text-sm">
              This submission has not been processed by this module yet.
            </span>
          </div>
        )}
        <SubmissionDetail
          identifier={moduleConfiguration.id}
          submission={viewSubmission}
          feedbacks={
            moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
              viewSubmission.id
            )?.suggestions ?? []
          }
        />
      </div>
    </div>
  );
}

export default function ConductBatchModuleExperimentWrapped({
  experiment,
  moduleConfiguration,
  viewSubmission,
}: ConductBatchModuleExperimentProps) {
  return (
    <ModuleProvider
      module={moduleConfiguration.moduleAndConfig.module}
      moduleConfig={moduleConfiguration.moduleAndConfig.moduleConfig}
    >
      <ConductBatchModuleExperiment
        experiment={experiment}
        moduleConfiguration={moduleConfiguration}
        viewSubmission={viewSubmission}
      />
    </ModuleProvider>
  );
}
