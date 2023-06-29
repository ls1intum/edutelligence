import { useEffect, useState } from "react";

import { Submission } from "@/model/submission";
import { Exercise } from "@/model/exercise";
import { ModuleMeta } from "@/model/health_response";
import { Mode } from "@/model/mode";
import ModuleResponse from "@/model/module_response";

import ExerciseSelect from "@/components/selectors/exercise_select";
import ModuleResponseView from "@/components/module_response_view";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionList from "@/components/submission_list";

import baseUrl from "@/helpers/base_url";

import { ModuleRequestProps } from ".";

async function sendSubmissions(
  mode: Mode,
  athenaUrl: string,
  athenaSecret: string,
  module: ModuleMeta,
  exercise: Exercise | undefined
): Promise<ModuleResponse | undefined> {
  if (!exercise) {
    alert("Please select an exercise");
    return;
  }
  const submissionsResponse = await fetch(
    `${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/submissions`
  );
  const submissions: Submission[] = await submissionsResponse.json();
  let response;
  try {
    const athenaSubmissionsUrl = `${athenaUrl}/modules/${module.type}/${module.name}/submissions`;
    response = await fetch(
      `${baseUrl}/api/athena_request?${new URLSearchParams({
        url: athenaSubmissionsUrl,
      })}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Secret": athenaSecret,
        },
        body: JSON.stringify({ exercise, submissions }),
      }
    );
  } catch (e) {
    console.error(e);
    alert(
      "Failed to send submissions to Athena: Failed to fetch. Is the URL correct?"
    );
    return;
  }
  if (!response.ok) {
    console.error(response);
    alert(`Athena responded with status code ${response.status}`);
    return {
      module_name: "Unknown",
      status: response.status,
      data: await response.text(),
    };
  }
  alert(`${submissions.length} submissions sent successfully!`);
  return {
    ...(await response.json()),
    status: response.status,
  };
}

export default function SendSubmissions({
  mode,
  athenaUrl,
  athenaSecret,
  module,
}: ModuleRequestProps) {
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(false);
  const [response, setResponse] = useState<ModuleResponse | undefined>(
    undefined
  );

  useEffect(() => {
    // Reset
    setResponse(undefined);
  }, [exercise]);

  useEffect(() => {
    setExercise(undefined);
  }, [module, mode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">Send Submissions</h3>
      <p className="text-gray-500 mb-4">
        Send all submissions for an exercise to Athena. This usually happens
        when the exercise deadline is reached in the LMS. The matching module
        for the exercise will receive the submissions at the function annotated
        with <code>@submission_consumer</code>.
      </p>
      <ExerciseSelect
        mode={mode}
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
      />
      {exercise && (
        <div className="space-y-1 mt-2">
          <ExerciseDetail exercise={exercise} mode={mode} />
          <SubmissionList exercise={exercise} mode={mode} />
        </div>
      )}
      <ModuleResponseView response={response} />
      <button
        className="bg-blue-500 text-white rounded-md p-2 mt-4"
        onClick={() => {
          setLoading(true);
          sendSubmissions(mode, athenaUrl, athenaSecret, module, exercise)
            .then(setResponse)
            .finally(() => setLoading(false));
        }}
        disabled={loading}
      >
        {loading ? "Loading..." : "Send Submissions"}
      </button>
    </div>
  );
}
