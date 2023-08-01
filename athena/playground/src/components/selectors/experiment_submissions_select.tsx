import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import { useState } from "react";

import useSubmissions from "@/hooks/playground/submissions";
import SubmissionList from "@/components/submission_list";

export type ExperimentSubmissions = {
  trainingSubmissions: Submission[] | undefined;
  testSubmissions: Submission[];
};

type ExperimentSubmissionsSelectProps = {
  exercise?: Exercise;
  experimentSubmissions?: ExperimentSubmissions;
  onChangeExperimentSubmissions: (
    experimentSubmissions: ExperimentSubmissions
  ) => void;
};

export default function ExperimentSubmissionsSelect({
  exercise,
  experimentSubmissions,
  onChangeExperimentSubmissions,
}: ExperimentSubmissionsSelectProps) {
  const { data, error, isLoading } = useSubmissions(exercise);

  const [moveSubmissionsNumber, setMoveSubmissionsNumber] = useState<number>(10);
  const [moveToTest, setMoveToTest] = useState<boolean>(true);

  if (!exercise) return null;
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  const isSubmissionUsed = (submission: Submission) =>
    experimentSubmissions?.trainingSubmissions?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    ) ||
    experimentSubmissions?.testSubmissions?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    );

  return (
    <div className="flex flex-col">
      <span className="text-lg font-bold">Submissions</span>
      <label className="flex items-center cursor-pointer">
        <input
          type="checkbox"
          checked={experimentSubmissions?.trainingSubmissions !== undefined}
          onChange={(e) => {
            if (e.target.checked) {
              onChangeExperimentSubmissions({
                trainingSubmissions: [],
                testSubmissions: experimentSubmissions?.testSubmissions ?? [],
              });
            } else {
              onChangeExperimentSubmissions({
                trainingSubmissions: undefined,
                testSubmissions: experimentSubmissions?.testSubmissions ?? [],
              });
            }
          }}
        />
        <div className="ml-2 text-gray-700 font-normal">
          Enable training/test data split
        </div>
      </label>

      <div className="flex flex-col items-start space-y-1 mt-2">
        <div className="flex gap-3">
          <label className="flex items-center cursor-pointer">
            <input
              className="ml-2 w-16 border border-gray-100 rounded-md p-1"
              type="number"
              step="0.5"
              value={moveSubmissionsNumber}
              onChange={(e) =>
                setMoveSubmissionsNumber(e.target.value ? parseInt(e.target.value) : 0)
              }
            />
            <div className="ml-2 text-gray-700 font-normal">Submissions</div>
          </label>
          {experimentSubmissions?.trainingSubmissions !== undefined && (
            <label className="flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={moveToTest}
                onChange={(e) => setMoveToTest(e.target.checked)}
              />
              <div className="ml-2 text-gray-700 font-normal">Target test</div>
            </label>
          )}
        </div>
        <button
          className="mt-2 text-sm text-primary-500 hover:text-primary-700 underline"
          onClick={() => {
            if (moveSubmissionsNumber === undefined) return;
            const submissionsToMove = data
              ?.filter((submission) => !isSubmissionUsed(submission))
              ?.slice(0, moveSubmissionsNumber);
            if (submissionsToMove === undefined) return;
            if (
              experimentSubmissions?.trainingSubmissions === undefined ||
              moveToTest
            ) {
              onChangeExperimentSubmissions({
                trainingSubmissions: experimentSubmissions?.trainingSubmissions,
                testSubmissions: [
                  ...(experimentSubmissions?.testSubmissions ?? []),
                  ...submissionsToMove,
                ],
              });
            } else if (
              experimentSubmissions?.trainingSubmissions !== undefined
            ) {
              onChangeExperimentSubmissions({
                trainingSubmissions: [
                  ...experimentSubmissions.trainingSubmissions,
                  ...submissionsToMove,
                ],
                testSubmissions: experimentSubmissions?.testSubmissions,
              });
            }
          }}
        >
          Move next {moveSubmissionsNumber} submissions
        </button>

        <button
          className="mt-2 text-sm text-primary-500 hover:text-primary-700 underline"
          onClick={() => {
            if (moveSubmissionsNumber === undefined) return;
            const submissionsToMove = data
              ?.filter((submission) => !isSubmissionUsed(submission))
              ?.sort(() => Math.random() - 0.5)
              .slice(0, moveSubmissionsNumber);
            if (submissionsToMove === undefined) return;
            if (
              experimentSubmissions?.trainingSubmissions === undefined ||
              moveToTest
            ) {
              onChangeExperimentSubmissions({
                trainingSubmissions: experimentSubmissions?.trainingSubmissions,
                testSubmissions: [
                  ...(experimentSubmissions?.testSubmissions ?? []),
                  ...submissionsToMove,
                ],
              });
            } else if (
              experimentSubmissions?.trainingSubmissions !== undefined
            ) {
              onChangeExperimentSubmissions({
                trainingSubmissions: [
                  ...experimentSubmissions.trainingSubmissions,
                  ...submissionsToMove,
                ],
                testSubmissions: experimentSubmissions?.testSubmissions,
              });
            }
          }}
        >
          Take random {moveSubmissionsNumber} submissions
        </button>

        <button
          className="mt-2 text-sm text-red-500 hover:text-red-700 underline"
          onClick={() =>
            onChangeExperimentSubmissions({
              trainingSubmissions:
                experimentSubmissions?.trainingSubmissions !== undefined
                  ? []
                  : undefined,
              testSubmissions: [],
            })
          }
        >
          Reset
        </button>
      </div>

      <div className="flex gap-2">
        <div className="flex-1 my-2 p-1">
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Unused
          </div>
          <SubmissionList
            submissions={
              data?.filter((submission) => !isSubmissionUsed(submission)) ?? []
            }
          />
        </div>
        {experimentSubmissions?.trainingSubmissions !== undefined && (
          <div className="flex-1 my-2 p-1">
            <div className="text-base font-medium border-b border-gray-300 mb-2">
              Training
            </div>
            <SubmissionList
              submissions={experimentSubmissions?.trainingSubmissions ?? []}
            />
          </div>
        )}
        <div className="flex-1 my-2 p-1">
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Test
          </div>
          <SubmissionList
            submissions={experimentSubmissions?.testSubmissions ?? []}
          />
        </div>
      </div>
    </div>
  );
}
