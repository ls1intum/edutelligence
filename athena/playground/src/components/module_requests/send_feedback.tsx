import type { Submission } from "@/model/submission";
import type { Mode } from "@/model/mode";
import type { Exercise } from "@/model/exercise";
import type { Feedback } from "@/model/feedback";
import type { ModuleResponse } from "@/model/module_response";
import type { ModuleMeta } from "@/model/health_response";

import { useEffect, useState } from "react";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import FeedbackSelect from "@/components/selectors/feedback_select";
import ModuleResponseView from "@/components/module_response_view";
import Disclosure from "@/components/disclosure";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import SubmissionList from "@/components/submission_list";

import baseUrl from "@/helpers/base_url";
import { useFeedbacks } from "@/helpers/client/get_data";

import { ModuleRequestProps } from ".";

async function sendFeedback(
  athenaUrl: string,
  athenaSecret: string,
  module: ModuleMeta,
  moduleConfig: any,
  exercise?: Exercise,
  submission?: Submission,
  feedback?: Feedback,
  alertAfterSuccess: boolean = true
): Promise<ModuleResponse | undefined> {
  if (!exercise) {
    alert("Please select an exercise");
    return;
  }
  if (!submission) {
    alert("Please select a submission");
    return;
  }
  if (!feedback) {
    alert("Please select a feedback");
    return;
  }
  try {
    const athenaFeedbackUrl = `${athenaUrl}/modules/${module.type}/${module.name}/feedback`;
    const response = await fetch(
      `${baseUrl}/api/athena_request?${new URLSearchParams({
        url: athenaFeedbackUrl,
      })}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Secret": athenaSecret,
          ...(moduleConfig && {
            "X-Module-Config": JSON.stringify(moduleConfig),
          }),
        },
        body: JSON.stringify({ exercise, submission, feedback }),
      }
    );
    if (response.status !== 200) {
      console.error(response);
      alert(`Athena responded with status code ${response.status}`);
      return {
        module_name: "Unknown",
        status: response.status,
        data: await response.text(),
      };
    }
    if (alertAfterSuccess) {
      alert("Feedback sent successfully!");
    }
    return await response.json();
  } catch (e) {
    console.error(e);
    alert(
      "Failed to send feedback to Athena: Failed to fetch. Is the URL correct?"
    );
  }
}

async function sendAllExerciseFeedbacks(
  mode: Mode,
  athenaUrl: string,
  athenaSecret: string,
  module: ModuleMeta,
  moduleConfig: any,
  exercise?: Exercise,
  submission?: Submission
): Promise<ModuleResponse[] | undefined> {
  if (!exercise) {
    alert("Please select an exercise");
    return;
  }
  const submissionResponse = await fetch(
    `${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/submissions`
  );
  if (submissionResponse.status !== 200) {
    console.error(submissionResponse);
    alert(`Failed to fetch submissions for exercise ${exercise.id}`);
    return;
  }
  const submissions: Submission[] = await submissionResponse.json();
  const feedbackResponse = await fetch(
    `${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/feedbacks`
  );
  if (feedbackResponse.status !== 200) {
    console.error(feedbackResponse);
    alert(`Failed to fetch feedbacks for exercise ${exercise.id}`);
    return;
  }
  let feedbacks: Feedback[] = await feedbackResponse.json();
  if (submission) {
    feedbacks = feedbacks.filter((f) => f.submission_id === submission.id);
  }
  if (feedbacks.length === 0) {
    alert(`No feedbacks found for ${submission ? "submission" : "exercise"}`);
    return;
  }
  const responses: ModuleResponse[] = [];
  for (const feedback of feedbacks) {
    const submission = submissions.find((s) => s.id === feedback.submission_id);
    const response = await sendFeedback(
      athenaUrl,
      athenaSecret,
      module,
      moduleConfig,
      exercise,
      submission!,
      feedback,
      false
    );
    if (response) {
      responses.push(response);
    } else {
      // something went wrong, abort
      return;
    }
  }
  alert(`${feedbacks.length} feedbacks sent`);
  return responses;
}

export default function SendFeedback({
  mode,
  athenaUrl,
  athenaSecret,
  module,
  moduleConfig,
}: ModuleRequestProps) {
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);

  const [isAllSubmissions, setIsAllSubmissions] = useState<boolean>(true);
  const [submission, setSubmission] = useState<Submission | undefined>(
    undefined
  );

  const [isAllFeedback, setIsAllFeedback] = useState<boolean>(true);
  const [feedback, setFeedback] = useState<Feedback | undefined>(undefined);

  const [loading, setLoading] = useState<boolean>(false);
  const [responses, setResponses] = useState<ModuleResponse[] | undefined>(
    undefined
  );

  const {
    feedbacks,
    isLoading: isFeedbackLoading,
    error: feedbackError,
  } = useFeedbacks(mode, exercise);

  useEffect(() => {
    // Reset
    setResponses(undefined);
    setIsAllSubmissions(true);
    setSubmission(undefined);
    setIsAllFeedback(true);
    setFeedback(undefined);
  }, [exercise]);

  useEffect(() => {
    // Reset
    setIsAllFeedback(true);
    setFeedback(undefined);
  }, [submission, isAllSubmissions]);

  useEffect(() => {
    setExercise(undefined);
  }, [module, mode]);

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
        mode={mode}
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
      />
      {exercise && (
        <>
          <SubmissionSelect
            mode={mode}
            exercise_id={exercise?.id}
            submission={submission}
            onChange={setSubmission}
            isAllSubmissions={isAllSubmissions}
            setIsAllSubmissions={setIsAllSubmissions}
          />
          {!isAllSubmissions && (
            <FeedbackSelect
              mode={mode}
              exercise_id={exercise?.id}
              submission_id={submission?.id}
              feedback={feedback}
              onChange={setFeedback}
              isAllFeedback={isAllFeedback}
              setIsAllFeedback={setIsAllFeedback}
            />
          )}
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} mode={mode} />
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
                <SubmissionList exercise={exercise} mode={mode} feedbacks={feedback ? [feedback] : feedbacks} />
              )
            )}
            {isFeedbackLoading && (
              <div className="text-gray-500 text-sm">Loading feedbacks...</div>
            )}
            {feedbackError && (
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
      {responses?.map((response, i) => (
        <ModuleResponseView key={i} response={response} />
      ))}
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600"
        onClick={() => {
          setLoading(true);
          if (isAllSubmissions) {
            sendAllExerciseFeedbacks(
              mode,
              athenaUrl,
              athenaSecret,
              module,
              moduleConfig,
              exercise!
            )
              .then(setResponses)
              .finally(() => setLoading(false));
          } else if (isAllFeedback) {
            sendAllExerciseFeedbacks(
              mode,
              athenaUrl,
              athenaSecret,
              module,
              moduleConfig,
              exercise!,
              submission!
            )
              .then(setResponses)
              .finally(() => setLoading(false));
          } else {
            sendFeedback(
              athenaUrl,
              athenaSecret,
              module,
              moduleConfig,
              exercise,
              submission,
              feedback
            )
              .then((resp) => setResponses(resp ? [resp] : undefined))
              .finally(() => setLoading(false));
          }
        }}
        disabled={loading}
      >
        {loading ? "Loading..." : "Send Feedback"}
      </button>
    </div>
  );
}
