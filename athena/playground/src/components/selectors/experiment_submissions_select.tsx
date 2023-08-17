import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import { useState } from "react";

import useSubmissions from "@/hooks/playground/submissions";
import useFeedbacks from "@/hooks/playground/feedbacks";
import SubmissionList from "@/components/submission_list";

type ExperimentSubmissionsSelectProps = {
  disabled?: boolean;
  exercise?: Exercise;
  trainingSubmissions?: Submission[];
  evaluationSubmissions?: Submission[];
  onChangeTrainingSubmissions: (submissions: Submission[] | undefined) => void;
  onChangeEvaluationSubmissions: (submissions: Submission[]) => void;
};

export default function ExperimentSubmissionsSelect({
  disabled,
  exercise,
  trainingSubmissions,
  evaluationSubmissions,
  onChangeTrainingSubmissions,
  onChangeEvaluationSubmissions,
}: ExperimentSubmissionsSelectProps) {
  const { data, error, isLoading } = useSubmissions(exercise);
  const { data: feedbacks } = useFeedbacks(exercise);

  const [sumbissionsSelectType, setSumbissionsSelectType] = useState<
    "random" | "next"
  >("random");
  const [moveSubmissionsNumber, setMoveSubmissionsNumber] =
    useState<number>(10);

  if (!exercise) return null;
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  const isSubmissionUsed = (submission: Submission) =>
    trainingSubmissions?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    ) ||
    evaluationSubmissions?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    );

  const excludedSubmissions =
    data?.filter((submission) => !isSubmissionUsed(submission)) ?? [];

  const takeFromSubmissions = (submissions: Submission[]) => {
    if (sumbissionsSelectType === "random") {
      return [...submissions]
        .sort(() => 0.5 - Math.random())
        .slice(0, moveSubmissionsNumber);
    } else {
      return [...submissions].slice(0, moveSubmissionsNumber);
    }
  };

  const moveSubmissions = (
    from: "training" | "evaluation" | "excluded",
    to: "training" | "evaluation" | "excluded"
  ) => {
    if (from === to || moveSubmissionsNumber <= 0) return;

    if (from === "excluded") {
      const moveSubmissions = takeFromSubmissions(excludedSubmissions);
      if (to === "training") {
        onChangeTrainingSubmissions([
          ...(trainingSubmissions ?? []),
          ...moveSubmissions,
        ]);
      } else if (to === "evaluation") {
        onChangeEvaluationSubmissions([
          ...(evaluationSubmissions ?? []),
          ...moveSubmissions,
        ]);
      }
    } else if (
      from === "training" &&
      trainingSubmissions
    ) {
      const moveSubmissions = takeFromSubmissions(trainingSubmissions);
      const newTrainingSubmissions =
        trainingSubmissions.filter(
          (submission) => !moveSubmissions.some((s) => s.id === submission.id)
        );
      if (to === "excluded") {
        onChangeTrainingSubmissions(newTrainingSubmissions);
      } else if (to === "evaluation") {
        onChangeTrainingSubmissions(newTrainingSubmissions);
        onChangeEvaluationSubmissions([
          ...(evaluationSubmissions ?? []),
          ...moveSubmissions,
        ]);
      }
    } else if (
      from === "evaluation" &&
      evaluationSubmissions
    ) {
      const moveSubmissions = takeFromSubmissions(evaluationSubmissions);
      const newEvaluationSubmissions =
        evaluationSubmissions.filter(
          (submission) => !moveSubmissions.some((s) => s.id === submission.id)
        );
      if (to === "excluded") {
        onChangeEvaluationSubmissions(newEvaluationSubmissions);
      } else if (to === "training") {
        onChangeEvaluationSubmissions(newEvaluationSubmissions);
        onChangeTrainingSubmissions([
          ...(trainingSubmissions ?? []),
          ...moveSubmissions,
        ]);
      }
    }
  };

  return (
    <div className="flex flex-col">
      <div className="text-lg font-bold">Submissions</div>
      {!disabled && (
        <div className="px-1">
          <label className="flex items-center cursor-pointer">
            <input
              disabled={disabled}
              type="checkbox"
              checked={trainingSubmissions !== undefined}
              onChange={(e) => {
                if (e.target.checked) {
                  onChangeTrainingSubmissions([]);
                } else {
                  onChangeTrainingSubmissions(undefined);
                }
              }}
            />
            <div className="ml-2 text-gray-700 font-normal">
              Enable training data
            </div>
          </label>
          <div className="flex flex-col items-start space-y-1 mt-2">
            <div className="flex items-center cursor-pointer text-gray-700 font-normal">
              Select
              <div className="flex flex-col items-start ml-2">
                <div className="flex items-center">
                  <label>
                    <input
                      type="radio"
                      value=""
                      className="mr-2"
                      checked={sumbissionsSelectType === "random"}
                      onChange={() => setSumbissionsSelectType("random")}
                    />
                    random
                  </label>
                </div>
                <div className="flex items-center">
                  <label>
                    <input
                      type="radio"
                      className="mr-2"
                      checked={sumbissionsSelectType === "next"}
                      onChange={() => setSumbissionsSelectType("next")}
                    />
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
        {!disabled && (
            <div className="justify-between flex items-center">
              {trainingSubmissions !== undefined && (
                <button
                  disabled={
                    Math.min(
                      moveSubmissionsNumber,
                      excludedSubmissions.length ?? 0
                    ) === 0
                  }
                  className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                  onClick={() => moveSubmissions("excluded", "training")}
                >
                  Move{" "}
                  {Math.min(
                    moveSubmissionsNumber,
                    excludedSubmissions.length ?? 0
                  )}{" "}
                  to Training →
                </button>
              )}
              <button
                disabled={
                  Math.min(
                    moveSubmissionsNumber,
                    excludedSubmissions.length ?? 0
                  ) === 0
                }
                className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-primary-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                onClick={() => moveSubmissions("excluded", "evaluation")}
              >
                Move{" "}
                {Math.min(
                  moveSubmissionsNumber,
                  excludedSubmissions.length ?? 0
                )}{" "}
                to Evaluation →
              </button>
            </div>
          )}
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Excluded ({excludedSubmissions.length} Submissions)
          </div>
          <p className="text-sm text-gray-500 mb-2">
            Submissions that are not used in the experiment.
          </p>
          <SubmissionList
            submissions={excludedSubmissions}
            feedbacks={feedbacks}
          />
        </div>
        {trainingSubmissions !== undefined && (
          <div className="flex-1 p-1 space-y-1">
            {!disabled && (
              <div className="justify-between flex items-center">
                <button
                  disabled={
                    Math.min(
                      moveSubmissionsNumber,
                      trainingSubmissions.length ?? 0
                    ) === 0
                  }
                  className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                  onClick={() => moveSubmissions("training", "excluded")}
                >
                  Move{" "}
                  {Math.min(
                    moveSubmissionsNumber,
                    trainingSubmissions.length ?? 0
                  )}{" "}
                  to Excluded →
                </button>
                <button
                  disabled={
                    Math.min(
                      moveSubmissionsNumber,
                      trainingSubmissions.length ?? 0
                    ) === 0
                  }
                  className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                  onClick={() => moveSubmissions("training", "evaluation")}
                >
                  Move{" "}
                  {Math.min(
                    moveSubmissionsNumber,
                    trainingSubmissions.length ?? 0
                  )}{" "}
                  to Evaluation →
                </button>
              </div>
            )}
            <div className="text-base font-medium border-b border-gray-300 mb-2">
              Training ({trainingSubmissions.length ?? 0}{" "}
              Submissions)
            </div>
            <p className="text-sm text-gray-500 mb-2">
              Sent for training before running evaluation.
            </p>
            <SubmissionList
              submissions={trainingSubmissions ?? []}
              feedbacks={feedbacks}
            />
          </div>
        )}
        <div className="flex-1 p-1 space-y-1">
        {!disabled && (
            <div className="justify-between flex items-center">
              <button
                disabled={
                  Math.min(
                    moveSubmissionsNumber,
                    evaluationSubmissions?.length ?? 0
                  ) === 0
                }
                className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                onClick={() => moveSubmissions("evaluation", "excluded")}
              >
                Move{" "}
                {Math.min(
                  moveSubmissionsNumber,
                  evaluationSubmissions?.length ?? 0
                )}{" "}
                to Excluded →
              </button>
              {trainingSubmissions !== undefined && (
                <button
                  disabled={
                    Math.min(
                      moveSubmissionsNumber,
                      evaluationSubmissions?.length ?? 0
                    ) === 0
                  }
                  className="rounded-md p-2 text-red-500 hover:text-red-600 hover:bg-red-100 disabled:text-gray-500 disabled:cursor-not-allowed disabled:hover:bg-gray-100"
                  onClick={() => moveSubmissions("evaluation", "training")}
                >
                  Move{" "}
                  {Math.min(
                    moveSubmissionsNumber,
                    evaluationSubmissions?.length ?? 0
                  )}{" "}
                  to Training →
                </button>
              )}
            </div>
          )}
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Evaluation (
            {evaluationSubmissions?.length ?? 0}{" "}
            Submissions)
          </div>
          <p className="text-sm text-gray-500 mb-2">
            Run the experiment on the evaluation submissions.
          </p>
          <SubmissionList
            submissions={evaluationSubmissions ?? []}
            feedbacks={feedbacks}
          />
        </div>
      </div>
    </div>
  );
}
