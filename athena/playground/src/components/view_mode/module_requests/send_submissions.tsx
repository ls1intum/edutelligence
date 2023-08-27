import type { Exercise } from "@/model/exercise";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";
import { useModule } from "@/hooks/module_context";
import useSendSubmissions from "@/hooks/athena/send_submissions";
import useSubmissions from "@/hooks/playground/submissions";

import ExerciseSelect from "@/components/selectors/exercise_select";
import ModuleResponseView from "@/components/module_response_view";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionList from "@/components/submission_list";

export default function SendSubmissions() {
  const { module } = useModule();
  const { dataMode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const { data: submissions, isLoading: isLoadingSubmissions, error: errorSubmissions } = useSubmissions(exercise);
  const { data: response, isLoading, error, mutate, reset } = useSendSubmissions({
    onError: (error) => {
      console.error(error);
      alert(`Failed to send submissions to Athena: ${error.message}. Is the URL correct?`);
    },
    onSuccess: () => {
      alert(`${submissions?.length} submissions sent successfully!`);
    },
  });

  useEffect(() => reset(), [exercise, reset]);
  useEffect(() => setExercise(undefined), [module, dataMode]);

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
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
        disabled={isLoading}
      />
      {exercise && (
        <div className="space-y-1 mt-2">
          <ExerciseDetail exercise={exercise} />
          {errorSubmissions && <div className="text-gray-500 text-sm">Failed to load submissions</div>}
          {isLoadingSubmissions && <div className="text-gray-500 text-sm">Loading submissions...</div>}
          {submissions && <SubmissionList submissions={submissions}/>}
        </div>
      )}
      <ModuleResponseView response={response ?? (error?.asModuleResponse ? error.asModuleResponse() : undefined)} />
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
          mutate({
            exercise,
            submissions,
          });
        }}
        disabled={!exercise || isLoading || isLoadingSubmissions}
      >
        {exercise
          ? isLoading || isLoadingSubmissions
            ? "Loading..."
            : "Send submissions"
          : "Please select an exercise"}
      </button>
    </div>
  );
}
