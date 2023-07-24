import type { Exercise } from "@/model/exercise";
import type { Mode } from "@/model/mode";
import type { ModuleMeta } from "@/model/health_response";
import type { Submission } from "@/model/submission";
import type { ModuleResponse } from "@/model/module_response";

import { useEffect, useState } from "react";

import ExerciseSelect from "@/components/selectors/exercise_select";
import ModuleResponseView from "@/components/module_response_view";
import ExerciseDetail from "@/components/details/exercise_detail";
import Disclosure from "@/components/disclosure";
import SubmissionDetail from "@/components/details/submission_detail";
import SubmissionList from "@/components/submission_list";

import baseUrl from "@/helpers/base_url";
import { useSubmissions } from "@/helpers/client/get_data";

import { ModuleRequestProps } from ".";

async function requestSubmissionSelection(
  mode: Mode,
  athenaUrl: string,
  athenaSecret: string,
  module: ModuleMeta,
  moduleConfig: any,
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
  try {
    const athenaSubmissionSelectUrl = `${athenaUrl}/modules/${module.type}/${module.name}/select_submission`;
    const response = await fetch(
      `${baseUrl}/api/athena_request?${new URLSearchParams({
        url: athenaSubmissionSelectUrl,
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
        body: JSON.stringify({
          exercise,
          submission_ids: submissions.map((submission) => submission.id),
        }),
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
    alert("Submission selection requested successfully!");
    return await response.json();
  } catch (e) {
    console.error(e);
    alert(
      "Failed to request submission selection from Athena: Failed to fetch. Is the URL correct?"
    );
  }
}

export default function SelectSubmission({
  mode,
  athenaUrl,
  athenaSecret,
  module,
  moduleConfig,
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

  const {
    submissions,
    isLoading: submissionsLoading,
    error: submissionsError,
  } = useSubmissions(mode, exercise);

  const responseSubmissionView = (response: ModuleResponse | undefined) => {
    if (!response || response.status !== 200 || typeof response.data !== "number") {
      return null;
    }
    const submissionId = response.data;
    const submission = submissions?.find(
      (submission) => submission.id === submissionId
    );
    return (
      submission && (
        <Disclosure
          title="Submission"
          openedInitially
          className={{ root: "ml-2" }}
        >
          <SubmissionDetail submission={submission} />
        </Disclosure>
      )
    );
  };

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">
        Request Submission Selection from Athena
      </h3>
      <p className="text-gray-500 mb-4">
        Request the submission to grade next out out of many submissions from
        Athena. The LMS would usually call this right before a tutor can start
        grading a submission. The matching module for the exercise will receive
        the request at the function annotated with{" "}
        <code>@submission_selector</code>. The playground currently only allows
        requesting a choice between all submissions of an exercise, but the LMS
        can also request a choice between a subset of submissions. <br />
        <b>
          This endpoint will only work properly after the submissions have been
          sent to Athena before.
        </b>
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
      <ModuleResponseView response={response}>
        {responseSubmissionView(response)}
      </ModuleResponseView>
      <button
        className="bg-primary-500 text-white rounded-md p-2 mt-4 hover:bg-primary-600"
        onClick={() => {
          setLoading(true);
          requestSubmissionSelection(
            mode,
            athenaUrl,
            athenaSecret,
            module,
            moduleConfig,
            exercise
          )
            .then(setResponse)
            .finally(() => setLoading(false));
        }}
        disabled={loading}
      >
        {loading ? "Loading..." : "Request Submission Selection"}
      </button>
    </div>
  );
}
