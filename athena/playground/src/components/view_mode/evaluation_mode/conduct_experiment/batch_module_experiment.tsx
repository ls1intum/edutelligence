import { ModuleProvider } from "@/hooks/module_context";
import { ModuleConfiguration } from "../configure_modules";
import { Experiment } from "../define_experiment";
import useBatchModuleExperiment from "@/hooks/batch_module_experiment";
import ModuleExperimentProgress from "./module_experiment_progress";
import type { Submission } from "@/model/submission";
import SubmissionDetail from "@/components/details/submission_detail";
import { useEffect } from "react";

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
  const moduleExperiment = useBatchModuleExperiment(experiment);

  useEffect(
    () => {
      console.log(`Feedbacks: ${moduleExperiment.data.submissionsWithFeedbackSuggestions.get(viewSubmission.id)?.suggestions.length}`, moduleExperiment.data.submissionsWithFeedbackSuggestions.get(viewSubmission.id)?.suggestions);
      console.log(moduleExperiment.data.submissionsWithFeedbackSuggestions)
    },
    [moduleExperiment.data.submissionsWithFeedbackSuggestions]
  )

  return (
    <div className="my-2 space-y-2">
      <ModuleExperimentProgress
        experiment={experiment}
        moduleExperiment={moduleExperiment}
      />
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
