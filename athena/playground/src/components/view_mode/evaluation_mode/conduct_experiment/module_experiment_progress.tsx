import { twMerge } from "tailwind-merge";
import { Experiment } from "../define_experiment";
import useBatchModuleExperiment, {
  ExperimentStep,
} from "@/hooks/batch_module_experiment";

type ModuleExperimentProgressProps = {
  experiment: Experiment;
  moduleExperiment: ReturnType<typeof useBatchModuleExperiment>;
};

export default function ModuleExperimentProgress({
  experiment,
  moduleExperiment,
}: ModuleExperimentProgressProps) {
  const data = moduleExperiment.data;
  const moduleRequests = moduleExperiment.moduleRequests;

  const stepToIndex = (step: ExperimentStep) => {
    const steps: ExperimentStep[] = [
      "sendingSubmissions",
      "sendingTrainingFeedbacks",
      "generatingFeedbackSuggestions",
      "finished",
    ];
    return steps.indexOf(step);
  };

  return (
    <ol className="w-full space-y-2">
      {/* Send Submissions */}
      <li className="flex items-center space-x-2">
        <span
          className={twMerge(
            "flex items-center justify-center w-6 h-6 border rounded-full shrink-0",
            stepToIndex(data.step) > 0
              ? "text-green-500 border-green-500"
              : "text-yellow-500 border-yellow-500"
          )}
        >
          1
        </span>
        <div
          className={twMerge(
            "flex flex-col",
            stepToIndex(data.step) > 0 ? "text-green-500" : "text-yellow-500"
          )}
        >
          <span className="font-medium">Send Submissions</span>
          {moduleRequests.sendSubmissions.isLoading && (
            <span className="text-xs text-gray-500 animate-pulse">
              Sending{" "}
              {(experiment.trainingSubmissions?.length ?? 0) +
                experiment.evaluationSubmissions.length}{" "}
              submissions...
            </span>
          )}
          {moduleRequests.sendSubmissions.isError && (
            <span className="text-xs text-red-500">
              {moduleRequests.sendSubmissions.error.message}
            </span>
          )}
          {moduleRequests.sendSubmissions.isSuccess && (
            <span className="text-xs text-green-500">
              Sent{" "}
              {(experiment.trainingSubmissions?.length ?? 0) +
                experiment.evaluationSubmissions.length}{" "}
              submissions
            </span>
          )}
        </div>
      </li>

      {/* Send Training Feedback */}
      {experiment.trainingSubmissions && (
        <li className="flex items-center space-x-2">
          <span
            className={twMerge(
              "flex items-center justify-center w-6 h-6 border rounded-full shrink-0",
              stepToIndex(data.step) > 1
                ? "text-green-500 border-green-500"
                : stepToIndex(data.step) === 1
                ? "text-yellow-500 border-yellow-500"
                : "text-gray-500 border-gray-500"
            )}
          >
            2
          </span>
          <div
            className={twMerge(
              "flex flex-col",
              stepToIndex(data.step) > 1
                ? "text-green-500"
                : stepToIndex(data.step) === 1
                ? "text-yellow-500"
                : "text-gray-500"
            )}
          >
            <span className="font-medium">Sending Training Feedback</span>
            {moduleRequests.sendFeedbacks.isLoading && (
              <span className="text-xs text-gray-500 animate-pulse">
                Sending feedback for training... (
                {data.sentTrainingSubmissions.length + 1}/
                {experiment.trainingSubmissions.length})
              </span>
            )}
            {moduleRequests.sendFeedbacks.isError && (
              <span className="text-xs text-red-500">
                {moduleRequests.sendFeedbacks.error.message}
              </span>
            )}
            {moduleRequests.sendFeedbacks.isSuccess && (
              <span className="text-xs text-green-500">
                Sent feedback for training (
                {data.sentTrainingSubmissions.length}/
                {experiment.trainingSubmissions.length})
              </span>
            )}
          </div>
        </li>
      )}

      {/* Generate Feedback Suggestions */}
      <li className="flex items-center space-x-2">
        <span
          className={twMerge(
            "flex items-center justify-center w-6 h-6 border rounded-full shrink-0",
            stepToIndex(data.step) > 2
              ? "text-green-500 border-green-500"
              : stepToIndex(data.step) === 2
              ? "text-yellow-500 border-yellow-500"
              : "text-gray-500 border-gray-500"
          )}
        >
          {experiment.trainingSubmissions ? 3 : 2}
        </span>
        <div
          className={twMerge(
            "flex flex-col",
            stepToIndex(data.step) > 2
              ? "text-green-500"
              : stepToIndex(data.step) === 2
              ? "text-yellow-500"
              : "text-gray-500"
          )}
        >
          <span className="font-medium">Generating Feedback Suggestions</span>
          {moduleRequests.requestFeedbackSuggestions.isLoading && (
            <span className="text-xs text-gray-500 animate-pulse">
              Generating feedback suggestions... (
              {data.submissionsWithFeedbackSuggestions.size + 1}/
              {experiment.evaluationSubmissions.length})
            </span>
          )}
          {moduleRequests.requestFeedbackSuggestions.isError && (
            <span className="text-xs text-red-500">
              {moduleRequests.requestFeedbackSuggestions.error.message}
            </span>
          )}
          {moduleRequests.requestFeedbackSuggestions.isSuccess && (
            <span className="text-xs text-green-500">
              Generated feedback suggestions (
              {data.submissionsWithFeedbackSuggestions.size}/
              {experiment.evaluationSubmissions.length})
            </span>
          )}
        </div>
      </li>
      <li className="flex items-center space-x-2">
        <span
          className={twMerge(
            "flex items-center justify-center w-6 h-6 border rounded-full shrink-0",
            stepToIndex(data.step) === 3
              ? "text-green-500 border-green-500"
              : "text-gray-500 border-gray-500"
          )}
        >
          {experiment.trainingSubmissions ? 4 : 3}
        </span>
        <div
          className={twMerge(
            "flex flex-col",
            stepToIndex(data.step) === 3 ? "text-green-500" : "text-gray-500"
          )}
        >
          <span className="font-medium">Finished</span>
        </div>
      </li>
    </ol>
  );
}
