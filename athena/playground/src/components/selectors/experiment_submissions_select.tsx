import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import useSubmissions from "@/hooks/playground/submissions";
import SubmissionList from "../submission_list";

export type ExperimentSubmissions = {
  training: Submission[] | undefined;
  test: Submission[];
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

  if (!exercise) return null;
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  const isSubmissionUsed = (submission: Submission) =>
    experimentSubmissions?.training?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    ) ||
    experimentSubmissions?.test?.some(
      (usedSubmission) => usedSubmission.id === submission.id
    );

  return (
    <div className="flex flex-col">
      <span className="text-lg font-bold">Submissions</span>
      <label className="flex items-center cursor-pointer">
        <input
          type="checkbox"
          checked={experimentSubmissions?.training !== undefined}
          onChange={(e) => {
            if (e.target.checked) {
              onChangeExperimentSubmissions({
                training: [],
                test: experimentSubmissions?.test ?? [],
              });
            } else {
              onChangeExperimentSubmissions({
                training: undefined,
                test: experimentSubmissions?.test ?? [],
              });
            }
          }}
        />
        <div className="ml-2 text-gray-700 font-normal">
          Enable training/test data split
        </div>
      </label>
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
        {experimentSubmissions?.training !== undefined && (
          <div className="flex-1 my-2 p-1">
            <div className="text-base font-medium border-b border-gray-300 mb-2">
              Training
            </div>
            <SubmissionList
              submissions={experimentSubmissions?.training ?? []}
            />
          </div>
        )}
        <div className="flex-1 my-2 p-1">
          <div className="text-base font-medium border-b border-gray-300 mb-2">
            Test
          </div>
          <SubmissionList submissions={experimentSubmissions?.test ?? []} />
        </div>
      </div>
    </div>
  );

  /*
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Submission</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={isAllSubmissions ? "all" : submission?.id || ""}
        disabled={disabled}
        onChange={(e) => {
          const value = e.target.value;
          if (value === "all") {
            setIsAllSubmissions!(true);
          } else {
            onChange(data!.find((sub: Submission) => sub.id === parseInt(e.target.value))!);
            if (setIsAllSubmissions) setIsAllSubmissions(false);
          }
        }}
      >
        <option value="" disabled>
          Select a submission
        </option>
        {isAllSubmissions !== undefined &&
          setIsAllSubmissions !== undefined && (
            <option
              key="all"
              value="all"
              onClick={() => setIsAllSubmissions(!isAllSubmissions)}
            >
              ✨ All submissions
            </option>
          )}
        {data?.map((sub: Submission) => {
          const contentPreview =
            (sub as TextSubmission)?.content ||
            (sub as ProgrammingSubmission)?.repository_url ||
            "?";
          return (
            <option key={sub.id} value={sub.id}>
              {sub.id} {contentPreview.substring(0, 80)}
            </option>
          );
        })}
      </select>
    </label>
  );
  */
}
