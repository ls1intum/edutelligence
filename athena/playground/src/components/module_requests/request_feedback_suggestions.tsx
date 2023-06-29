import { useEffect, useState } from "react";

import { Submission } from "@/model/submission";
import { Exercise } from "@/model/exercise";
import { ModuleMeta } from "@/model/health_response";
import ModuleResponse from "@/model/module_response";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import ModuleResponseView from "@/components/module_response_view";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import Disclosure from "@/components/disclosure";

import baseUrl from "@/helpers/base_url";

import { ModuleRequestProps } from ".";

async function requestFeedbackSuggestions(
  athenaUrl: string,
  athenaSecret: string,
  module: ModuleMeta,
  exercise: Exercise | undefined,
  submission: Submission | undefined
): Promise<ModuleResponse | undefined> {
  if (!exercise) {
    alert("Please select an exercise");
    return;
  }
  if (!submission) {
    alert("Please select a submission");
    return;
  }
  try {
    const athenaFeedbackUrl = `${athenaUrl}/modules/${module.type}/${module.name}/feedback_suggestions`;
    const response = await fetch(
      `${baseUrl}/api/athena_request?${new URLSearchParams({
        url: athenaFeedbackUrl,
      })}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Secret": athenaSecret,
        },
        body: JSON.stringify({ exercise, submission }),
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
    alert("Feedback suggestions requested successfully!");
    return await response.json();
  } catch (e) {
    console.error(e);
    alert(
      "Failed to request feedback suggestions from Athena: Failed to fetch. Is the URL correct?"
    );
  }
}

export default function RequestFeedbackSuggestions({
  mode,
  athenaUrl,
  athenaSecret,
  module,
}: ModuleRequestProps) {
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [submission, setSubmission] = useState<Submission | undefined>(
    undefined
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [response, setResponse] = useState<ModuleResponse | undefined>(
    undefined
  );

  useEffect(() => {
    // Reset
    setResponse(undefined);
    setSubmission(undefined);
  }, [exercise]);

  useEffect(() => {
    setExercise(undefined);
  }, [module, mode]);

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
          <SubmissionDetail submission={submission} feedbacks={feedbacks} />
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
          />
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} mode={mode} />
            {submission && (
              <Disclosure title="Submission">
                <SubmissionDetail submission={submission} />
              </Disclosure>
            )}
          </div>
        </>
      )}
      <ModuleResponseView response={response}>
        {responseSubmissionView(response)}
      </ModuleResponseView>
      <button
        className="bg-blue-500 text-white rounded-md p-2 mt-4"
        onClick={() => {
          setLoading(true);
          requestFeedbackSuggestions(
            athenaUrl,
            athenaSecret,
            module,
            exercise,
            submission
          )
            .then(setResponse)
            .finally(() => setLoading(false));
        }}
        disabled={loading}
      >
        {loading ? "Loading..." : "Request Feedback Suggestions"}
      </button>
    </div>
  );
}
