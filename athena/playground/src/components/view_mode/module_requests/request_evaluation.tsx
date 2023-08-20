import type ModuleResponse from "@/model/module_response";
import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";
import type { Feedback } from "@/model/feedback";

import { useEffect, useState } from "react";

import { useModule } from "@/hooks/module_context";
import { useBaseInfo } from "@/hooks/base_info_context";
import useRequestEvaluaion from "@/hooks/athena/request_evaluation";
import useFeedbacks from "@/hooks/playground/feedbacks";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import ModuleResponseView from "@/components/module_response_view";
import Disclosure from "@/components/disclosure";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import SubmissionList from "@/components/submission_list";
import { AthenaError } from "@/hooks/athena_fetcher";

export default function RequestEvaluation() {
  const { module } = useModule();
  const { dataMode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [submission, setSubmission] = useState<Submission | undefined>(undefined);

  const [predictedFeedbacks, setPredictedFeedbacks] = useState<Feedback[]>([]);

  const { data: trueFeedbacks, isLoading: isLoadingTrueFeedbacks, error: errorTrueFeedbacks } = useFeedbacks(exercise, submission);

  const { data: response, isLoading, error, mutate, reset } = useRequestEvaluaion();

  useEffect(() => setExercise(undefined), [module, dataMode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">Request Evaluation from Athena</h3>
      <p className="text-gray-500 mb-4">
        {/* TODO */}
         <code>@evaluation_provider</code>.
      </p>
      <ExerciseSelect
        exerciseType={module.type}
        exercise={exercise}
        onChange={(exercise) => {
          setExercise(exercise);
          reset();
          setSubmission(undefined);
          setPredictedFeedbacks([]);
        }}
        disabled={isLoading}
      />
      {exercise && (
        <>
          <SubmissionSelect
            exercise={exercise}
            submission={submission}
            onChange={(submission) => {
              setSubmission(submission);
              setPredictedFeedbacks([]);
            }}
            disabled={isLoading}
          />
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} />
            {submission && (
              trueFeedbacks ? (
              <Disclosure title="True Feedbacks">
                <SubmissionDetail
                  submission={submission}
                  feedbacks={trueFeedbacks.filter(
                    (f) => f.submission_id === submission.id
                  )}
                />
              </Disclosure>
            ) : (
              <div className="text-gray-500 text-sm">
                No true feedbacks available
              </div>
            )
            )}
            {submission && (
              <Disclosure title="Predicted Feedbacks">
                <SubmissionDetail
                  submission={submission}
                  feedbacks={predictedFeedbacks.filter(
                    (f) => f.submission_id === submission.id
                  )}
                  onFeedbacksChange={setPredictedFeedbacks}
                />
              </Disclosure>
            )}
            {isLoadingTrueFeedbacks && (
              <div className="text-gray-500 text-sm">Loading feedbacks...</div>
            )}
            {errorTrueFeedbacks && (
              <div className="text-red-500 text-sm">
                Failed to load feedbacks
              </div>
            )}
          </div>
        </>
      )}
      <ModuleResponseView response={response ?? (error?.asModuleResponse ? error.asModuleResponse() : undefined)}>
        {/* {responseSubmissionView(response)} */}
      </ModuleResponseView>
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
        onClick={async () => {
          if (!exercise) {
            alert("Please select an exercise");
            return;
          }
          if (!submission) {
            alert("Please select a submission");
            return;
          }
          if (!trueFeedbacks) {
            alert("Please wait for the true feedbacks to load");
            return;
          }

          mutate({
            exercise,
            submission,
            trueFeedbacks,
            predictedFeedbacks,
          });
        }}
        disabled={
          !exercise || isLoading || isLoadingTrueFeedbacks
        }
      >
        {exercise
          ? isLoading || isLoadingTrueFeedbacks
            ? "Loading..."
            : "Request evaluation"
          : "Please select an exercise"}
      </button>
    </div>
  );
}
