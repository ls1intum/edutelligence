import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";
import type { Feedback } from "@/model/feedback";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";
import { useSendFeedbacks } from "@/hooks/athena/send_feedback";
import useSubmissions from "@/hooks/playground/submissions";
import useFeedbacks from "@/hooks/playground/feedbacks";
import { useModule } from "@/hooks/module_context";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import FeedbackSelect from "@/components/selectors/feedback_select";
import ModuleResponseView from "@/components/module_response_view";
import Disclosure from "@/components/disclosure";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import SubmissionList from "@/components/submission_list";

export default function SendFeedback() {
  const { module } = useModule();
  const { dataMode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [isAllSubmissions, setIsAllSubmissions] = useState<boolean>(true);
  const [submission, setSubmission] = useState<Submission | undefined>(undefined);
  const [isAllFeedback, setIsAllFeedback] = useState<boolean>(true);
  const [feedback, setFeedback] = useState<Feedback | undefined>(undefined);

  const { data: submissions, isLoading: isLoadingSubmissions, error: errorSubmissions } = useSubmissions(exercise);
  const { data: feedbacks, isLoading: isLoadingFeedbacks, error: errorFeedbacks} = useFeedbacks(exercise);
  const { data: responses, isLoading, error, mutate, reset } = useSendFeedbacks({
    onError: (error) => {
      console.error(error);
      alert(`Failed to send feedback(s) to Athena: ${error.message}. Is the URL correct?`);
    },
    onSuccess: (responses) => {
      alert(`${responses?.length} feedback(s) sent successfully!`);
    },
  });

  // Handle resets with useEffect to avoid stale state
  useEffect(() => {
    reset();
    setIsAllSubmissions(true);
    setSubmission(undefined);
    setIsAllFeedback(true);
    setFeedback(undefined);
  }, [exercise, reset]);
  useEffect(() => {
    setIsAllFeedback(true);
    setFeedback(undefined);
  }, [submission, isAllSubmissions]);
  useEffect(() =>  setExercise(undefined), [module, dataMode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">Send Feedback to Athena</h3>
      <p className="text-gray-500 mb-4">
        Send a single given feedback to Athena, or all feedback for the whole
        exercise. This usually happens when someone gives feedback on the
        submission in the LMS. The matching module for the exercise will receive
        the feedback at the function annotated with{" "}
        <code>@feedback_consumer</code>.
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
            isAllSubmissions={isAllSubmissions}
            setIsAllSubmissions={setIsAllSubmissions}
            disabled={isLoading}
          />
          {!isAllSubmissions && (
            <FeedbackSelect
              exercise={exercise}
              submission={submission}
              feedback={feedback}
              onChange={setFeedback}
              isAllFeedback={isAllFeedback}
              setIsAllFeedback={setIsAllFeedback}
              disabled={isLoading}
            />
          )}
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} />
            {submission ? (
              <Disclosure title="Submission">
                <SubmissionDetail
                  submission={submission}
                  feedbacks={feedback ? [feedback] : feedbacks?.filter(
                    (f) => f.submission_id === submission.id
                  )}
                />
              </Disclosure>
            ) : (
              isAllFeedback && (
                <>
                  {errorSubmissions && <div className="text-gray-500 text-sm">Failed to load submissions</div>}
                  {isLoadingSubmissions && <div className="text-gray-500 text-sm">Loading submissions...</div>}
                  {submissions && <SubmissionList submissions={submissions} feedbacks={feedback ? [feedback] : feedbacks}/>}
                </>
              )
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
              exercise. This will send a request for each feedback of each
              submission.
            </div>
          )}
          {!isAllSubmissions && isAllFeedback && (
            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 text-sm text-yellow-700 mt-2">
              You are about to send all feedback for the selected submission.
              This will send a request for each feedback of the submission.
            </div>
          )}
        </>
      )}
      {responses?.map((response, i) => (<ModuleResponseView key={i} response={response} />))}
      {error?.asModuleResponse && (<ModuleResponseView response={error.asModuleResponse()} />)}
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
        onClick={() => {
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

          let items: { exercise: Exercise; submission: Submission; feedback: Feedback }[] = [];
          if (!isAllFeedback) {
            // Sending single feedback for single submission
            if (submission && feedback) {
              items = [{ exercise, submission, feedback }];
            } else {
              alert("Please select a submission and feedback");
              return;
            }
          } else {
            // Sending all feedbacks for single submission or all submissions
            const submissionsToSend = isAllSubmissions ? submissions : [submission!];
            submissionsToSend.forEach((submission) => {
              const feedbacksToSend = feedbacks.filter(
                (f) => f.submission_id === submission.id
              );
              feedbacksToSend.forEach((feedback) => {
                items.push({ exercise, submission, feedback });
              });
            });
          }
          if (items.length === 0) {
            alert("No feedback to send");
            return;
          }
          mutate(items);
        }}
        disabled={!exercise || isLoading || isLoadingSubmissions || isLoadingFeedbacks}
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
