import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";
import type ModuleResponse from "@/model/module_response";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";
import useRequestFeedbackSuggestions from "@/hooks/athena/request_feedback_suggestions";
import { useModule } from "@/hooks/module_context";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import ModuleResponseView from "@/components/module_response_view";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import Disclosure from "@/components/disclosure";

export default function RequestFeedbackSuggestions() {
  const { module } = useModule();
  const { dataMode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [submission, setSubmission] = useState<Submission | undefined>(
    undefined
  );

  const {
    data: response,
    isLoading,
    error,
    mutate,
    reset,
  } = useRequestFeedbackSuggestions({
    onError: (error) => {
      console.error(error);
      alert(
        `Failed to request feedback suggestions from Athena: ${error.message}. Is the URL correct?`
      );
    },
    onSuccess: () => {
      alert(`Feedback suggestions requested successfully!`);
    },
  });

  // Handle resets with useEffect to avoid stale state
  useEffect(() => {
    reset();
    setSubmission(undefined);
  }, [exercise, reset]);
  useEffect(() => setExercise(undefined), [module, dataMode]);

  const responseSubmissionView = (response: ModuleResponse | undefined) => {
    if (!response || response.status !== 200) {
      return null;
    }

    const feedbacks = response.data;
    return (
      submission && (
        <Disclosure
          title="Submission with Feedback Suggestions"
          openedInitially
          className={{ root: "ml-2" }}
        >
          <SubmissionDetail identifier="suggestions" submission={submission} feedbacks={feedbacks} />
        </Disclosure>
      )
    );
  };

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">
        Request Feedback Suggestions from Athena
      </h3>
      <p className="text-gray-500 mb-4">
        Request a list of feedback suggestions from Athena for the selected
        submission. The LMS would usually call this when a tutor starts grading
        a submission. You should get a list of all submissions that are not
        graded yet. The matching module for the exercise will receive the
        request at the function annotated with <code>@feedback_provider</code>.
      </p>
      <ExerciseSelect
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
        disabled={isLoading}
      />
      {exercise && (
        <>
          <SubmissionSelect
            exercise={exercise}
            submission={submission}
            onChange={setSubmission}
            disabled={isLoading}
          />
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} />
            {submission && (
              <Disclosure title="Submission">
                <SubmissionDetail identifier="suggestions_submission" submission={submission} />
              </Disclosure>
            )}
          </div>
        </>
      )}
      <ModuleResponseView response={response ?? (error?.asModuleResponse ? error.asModuleResponse() : undefined)}>
        {responseSubmissionView(response)}
      </ModuleResponseView>
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
        onClick={() => {
          if (!exercise) {
            alert("Please select an exercise");
            return;
          }
          if (!submission) {
            alert("Please select a submission");
            return;
          }
          mutate({
            exercise,
            submission,
          });
        }}
        disabled={!exercise || !submission || isLoading}
      >
        {exercise && submission
          ? isLoading
            ? "Loading..."
            : "Request feedback suggestions"
          : exercise
          ? "Please select a submission"
          : "Please select an exercise"}
      </button>
      
    </div>
  );
}
