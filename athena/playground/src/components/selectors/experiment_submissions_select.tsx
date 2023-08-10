import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import { useState } from "react";

import useSubmissions from "@/hooks/playground/submissions";
import useFeedbacks from "@/hooks/playground/feedbacks";
import SubmissionList from "@/components/submission_list";

export type ExperimentSubmissions = {
  trainingSubmissions: Submission[] | undefined;
  testSubmissions: Submission[];
};

type ExperimentSubmissionsSelectProps = {
  disabled?: boolean;
  exercise?: Exercise;
  experimentSubmissions?: ExperimentSubmissions;
  onChangeExperimentSubmissions: (
    experimentSubmissions: ExperimentSubmissions
  ) => void;
};

export default function ExperimentSubmissionsSelect({
  disabled,
  exercise,
  experimentSubmissions,
  onChangeExperimentSubmissions,
}: ExperimentSubmissionsSelectProps) {
  const { data, error, isLoading } = useSubmissions(exercise);
  const { data: feedbacks } = useFeedbacks(exercise);

  const [moveSubmissionsNumber, setMoveSubmissionsNumber] =
    useState<number>(10);
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

  const moveNext = () => {
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
    } else if (experimentSubmissions?.trainingSubmissions !== undefined) {
      onChangeExperimentSubmissions({
        trainingSubmissions: [
          ...experimentSubmissions.trainingSubmissions,
          ...submissionsToMove,
        ],
        testSubmissions: experimentSubmissions?.testSubmissions,
      });
    }
  };

  const takeRandom = () => {
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
    } else if (experimentSubmissions?.trainingSubmissions !== undefined) {
      onChangeExperimentSubmissions({
        trainingSubmissions: [
          ...experimentSubmissions.trainingSubmissions,
          ...submissionsToMove,
        ],
        testSubmissions: experimentSubmissions?.testSubmissions,
      });
    }
  };

  const excludedSubmissions =
    data?.filter((submission) => !isSubmissionUsed(submission)) ?? [];

  return (
    <div className="flex flex-col">
      <div className="text-lg font-bold">Submissions</div>
      {!disabled && (
        <div className="px-1">
          <label className="flex items-center cursor-pointer">
            <input
              disabled={disabled}
              type="checkbox"
              checked={experimentSubmissions?.trainingSubmissions !== undefined}
              onChange={(e) => {
                if (e.target.checked) {
                  onChangeExperimentSubmissions({
                    trainingSubmissions: [],
                    testSubmissions:
                      experimentSubmissions?.testSubmissions ?? [],
                  });
                } else {
                  onChangeExperimentSubmissions({
                    trainingSubmissions: undefined,
                    testSubmissions:
                      experimentSubmissions?.testSubmissions ?? [],
                  });
                }
              }}
            />
            <div className="ml-2 text-gray-700 font-normal">
              Enable training data
            </div>
          </label>
          <div className="flex flex-col items-start space-y-1 mt-2">
            <div className="flex items-center cursor-pointer text-gray-700 font-normal">
              Move
              <div className="flex flex-col items-start ml-2">
                <div className="flex items-center">
                  <input
                    id="default-radio-1"
                    type="radio"
                    value=""
                    name="default-radio"
                  />
                  <label htmlFor="default-radio-1" className="ml-2">
                    random
                  </label>
                </div>
                <div className="flex items-center">
                  <input
                    checked
                    id="default-radio-2"
                    type="radio"
                    value=""
                    name="default-radio"
                  />
                  <label htmlFor="default-radio-2" className="ml-2">
                    next
                  </label>
                </div>
              </div>
              <label>
                <input
                  disabled={disabled}
                  className="mx-2 w-16 border border-gray-100 rounded-md p-1"
                  type="number"
                  step="1"
                  value={moveSubmissionsNumber}
                  onChange={(e) =>
                    setMoveSubmissionsNumber(
                      Math.max(e.target.value ? parseInt(e.target.value) : 0, 0)
                    )
                  }
                />
                submissions
              </label>
            </div>
          </div>
        </div>
      )}
      <div className="flex gap-2">
        <div className="flex-1 p-1 space-y-1">
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Excluded ({excludedSubmissions.length} Submissions)
          </div>
          {!disabled && (
            <div className="border-b border-gray-200 pb-1 justify-between flex items-center">
              <div className="flex flex-col">
                <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                  {moveSubmissionsNumber} Training →
                </button>
                <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                  {moveSubmissionsNumber} Training ←
                </button>
              </div>
              <div className="flex flex-col">
                <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                  {moveSubmissionsNumber} Evaluation →
                </button>
                <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                  {moveSubmissionsNumber} Evaluation ←
                </button>
              </div>
            </div>
          )}
          <p className="text-sm text-gray-500 mb-2">
            Submissions that are not used in the experiment.
          </p>
          <SubmissionList
            submissions={excludedSubmissions}
            feedbacks={feedbacks}
          />
        </div>
        {experimentSubmissions?.trainingSubmissions !== undefined && (
          <div className="flex-1 p-1 space-y-1">
            <div className="text-base font-medium border-b border-gray-300 mb-2">
              Training ({experimentSubmissions?.trainingSubmissions.length ?? 0}{" "}
              Submissions)
            </div>
            {!disabled && (
              <div className="border-b border-gray-200 pb-1 justify-between flex items-center">
                <div className="flex flex-col">
                  <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                    {moveSubmissionsNumber} Excluded →
                  </button>
                  <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                    {moveSubmissionsNumber} Excluded ←
                  </button>
                </div>
                <div className="flex flex-col">
                  <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                    {moveSubmissionsNumber} Evaluation →
                  </button>
                  <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                    {moveSubmissionsNumber} Evaluation ←
                  </button>
                </div>
              </div>
            )}
            <p className="text-sm text-gray-500 mb-2">
              Sent for training before running evaluation.
            </p>
            <SubmissionList
              submissions={experimentSubmissions?.trainingSubmissions ?? []}
              feedbacks={feedbacks}
            />
          </div>
        )}
        <div className="flex-1 p-1 space-y-1">
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Evaluation ({experimentSubmissions?.testSubmissions.length ?? 0}{" "}
            Submissions)
          </div>
          {!disabled && (
            <div className="border-b border-gray-200 pb-1 justify-between flex items-center">
              <div className="flex flex-col">
                <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                  {moveSubmissionsNumber} Excluded →
                </button>
                <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                  {moveSubmissionsNumber} Excluded ←
                </button>
              </div>
              <div className="flex flex-col">
                <button className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100">
                  {moveSubmissionsNumber} Training →
                </button>
                <button className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100">
                  {moveSubmissionsNumber} Training ←
                </button>
              </div>
            </div>
          )}
          <p className="text-sm text-gray-500 mb-2">
            Run the experiment on the evaluation submissions.
          </p>
          <SubmissionList
            submissions={experimentSubmissions?.testSubmissions ?? []}
            feedbacks={feedbacks}
          />
        </div>
      </div>
    </div>
  );
}
