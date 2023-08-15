import type ModuleResponse from "@/model/module_response";
import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";
import type { Feedback } from "@/model/feedback";

import { useEffect, useState } from "react";

import { useModule } from "@/hooks/module_context";
import { useBaseInfo } from "@/hooks/base_info_context";
import { useSendFeedbacks } from "@/hooks/athena/send_feedbacks";
import useSubmissions from "@/hooks/playground/submissions";
import useFeedbacks from "@/hooks/playground/feedbacks";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import ModuleResponseView from "@/components/module_response_view";
import Disclosure from "@/components/disclosure";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import SubmissionList from "@/components/submission_list";
import { AthenaError } from "@/hooks/athena_fetcher";

export default function SendFeedbacks() {
  const { module } = useModule();
  const { dataMode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [isAllSubmissions, setIsAllSubmissions] = useState<boolean>(true);
  const [selectedSubmission, setSelectedSubmission] = useState<Submission | undefined>(undefined);

  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [removedFeedbackIds, setRemovedFeedbackIds] = useState<number[]>([]);
  const [responses, setResponses] = useState<(ModuleResponse | undefined)[]>([]);

  const setFeedbacksAndTrackChanges = (newFeedbacks: Feedback[]) => {
    const storedFeedbackIds = new Set<number>(
      storedFeedbacks?.map((f) => f.id) ?? []
    );

    setFeedbacks(newFeedbacks);
    const removedIds = new Set<number>(
      feedbacks.map((f) => f.id).filter((id) => storedFeedbackIds.has(id))
    );
    newFeedbacks.forEach((f) => removedIds.delete(f.id));
    removedFeedbackIds.forEach((id) => removedIds.add(id));
    setRemovedFeedbackIds(Array.from(removedIds));
  };

  const {
    data: submissions,
    isLoading: isLoadingSubmissions,
    error: errorSubmissions,
  } = useSubmissions(exercise);
  const {
    data: storedFeedbacks,
    isLoading: isLoadingFeedbacks,
    error: errorFeedbacks,
  } = useFeedbacks(exercise, selectedSubmission, {
    onSuccess: (fetchFeedbacks) => {
      const ignoreIds = new Set<number>(removedFeedbackIds);
      feedbacks.forEach((f) => ignoreIds.add(f.id));
      setFeedbacks([
        ...fetchFeedbacks.filter((f) => !ignoreIds.has(f.id)),
        ...feedbacks,
      ]);
    },
  });

  const { isLoading, error, mutateAsync, reset } = useSendFeedbacks();

  const feedbacksAreChanged =
    removedFeedbackIds.length > 0 || feedbacks.some((f) => f.isChanged);
  const resetFeedbacks = () => {
    setFeedbacks(storedFeedbacks ?? []);
    setRemovedFeedbackIds([]);
  };

  // Handle resets with useEffect to avoid stale state
  useEffect(() => setExercise(undefined), [module, dataMode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">Send Feedbacks to Athena</h3>
      <p className="text-gray-500 mb-4">
        Send given feedbacks to Athena, or all feedbacks for the whole exercise.
        This usually happens when someone gives feedbacks on the submission in
        the LMS. The matching module for the exercise will receive the feedbacks
        at the function annotated with <code>@feedback_consumer</code>.
      </p>
      <ExerciseSelect
        exerciseType={module.type}
        exercise={exercise}
        onChange={(exercise) => {
          setExercise(exercise);
          reset();
          setResponses([]);
          setIsAllSubmissions(true);
          setSelectedSubmission(undefined);
          resetFeedbacks();
        }}
        disabled={isLoading}
      />
      {exercise && (
        <>
          <SubmissionSelect
            exercise={exercise}
            submission={selectedSubmission}
            onChange={(submission) => {
              setSelectedSubmission(submission);
              resetFeedbacks();
            }}
            isAllSubmissions={isAllSubmissions}
            setIsAllSubmissions={setIsAllSubmissions}
            disabled={isLoading}
          />
          <div className="space-y-1 mt-2">
            {feedbacksAreChanged && (
              <button
                className="bg-red-100 text-red-800 rounded-md p-2 hover:bg-red-200 hover:text-red-900"
                onClick={() => resetFeedbacks()}
              >
                Reset Changed Feedbacks
              </button>
            )}
            <ExerciseDetail exercise={exercise} />
            {selectedSubmission && !isAllSubmissions ? (
              <Disclosure title="Submission">
                <SubmissionDetail
                  submission={selectedSubmission}
                  feedbacks={feedbacks.filter(
                    (f) => f.submission_id === selectedSubmission.id
                  )}
                  onFeedbacksChange={setFeedbacksAndTrackChanges}
                />
              </Disclosure>
            ) : (
              submissions && (
                <SubmissionList
                  submissions={submissions}
                  feedbacks={feedbacks}
                  onFeedbacksChange={setFeedbacksAndTrackChanges}
                />
              )
            )}
            {isLoadingSubmissions && (
              <div className="text-gray-500 text-sm">
                Loading submissions...
              </div>
            )}
            {errorSubmissions && (
              <div className="text-gray-500 text-sm">
                Failed to load submissions
              </div>
            )}
            {isLoadingFeedbacks && (
              <div className="text-gray-500 text-sm">Loading feedbacks...</div>
            )}
            {errorFeedbacks && (
              <div className="text-red-500 text-sm">
                Failed to load feedbacks
              </div>
            )}
          </div>
          {isAllSubmissions && (
            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 text-sm text-yellow-700 mt-2">
              You are about to send feedback for all submissions of this
              exercise. This will send a request for each submission.
            </div>
          )}
        </>
      )}
      {responses?.map((response, i) => (
        <ModuleResponseView key={i} response={response} />
      ))}
      {error?.asModuleResponse && (
        <ModuleResponseView response={error.asModuleResponse()} />
      )}
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
        onClick={async () => {
          setResponses([]);
          if (!exercise) {
            alert("Please select an exercise");
            return;
          }
          if (!submissions) {
            alert("Failed to fetch submissions or no submissions found");
            return;
          }
          if (!feedbacks) {
            alert("Failed to fetch feedbacks or no feedbacks found");
            return;
          }

          let items: { submission: Submission; feedbacks: Feedback[] }[] = [];
          if (isAllSubmissions) {
            submissions.forEach((submission) => {
              items.push({
                submission,
                feedbacks: feedbacks.filter(
                  (f) => f.submission_id === submission.id
                ),
              });
            });
          } else {
            if (!selectedSubmission) {
              alert("Please select a submission");
              return;
            }
            items.push({ submission: selectedSubmission, feedbacks });
          }
          items = items.filter((item) => item.feedbacks.length > 0);

          if (items.length === 0) {
            alert("No feedback to send");
            return;
          }

          let errors: AthenaError[] = [];
          let responses: (ModuleResponse | undefined)[] = [];
          let sentFeedbacksCount = 0;
          for (const { submission, feedbacks } of items) {
            try {
              await mutateAsync(
                {
                  exercise,
                  submission,
                  feedbacks,
                },
                {
                  onSettled: (response) => {
                    responses.push(response);
                  },
                }
              );
              sentFeedbacksCount += feedbacks.length;
            } catch (error) {
              errors.push(error as AthenaError);
            }
          }
          if (errors.length > 0) {
            alert(
              `Failed to send feedbacks to Athena: ${errors
                .map((e) => e.message)
                .join(", ")}. Is the URL correct?`
            );
          } else {
            alert(
              `${sentFeedbacksCount} feedback(s) in ${items.length} submission(s) sent sucessfully!`
            );
          }
          setResponses(responses);
        }}
        disabled={
          !exercise || isLoading || isLoadingSubmissions || isLoadingFeedbacks
        }
      >
        {exercise
          ? isLoading || isLoadingSubmissions || isLoadingFeedbacks
            ? "Loading..."
            : "Send feedback"
          : "Please select an exercise"}
      </button>
    </div>
  );
}
