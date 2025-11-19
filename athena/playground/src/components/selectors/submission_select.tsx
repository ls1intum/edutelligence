import type { ProgrammingSubmission, Submission, TextSubmission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import useSubmissions from "@/hooks/playground/submissions";

type SubmissionSelectProps = {
  exercise?: Exercise;
  submission?: Submission;
  onChange: (submission: Submission) => void;
  isAllSubmissions?: boolean;
  setIsAllSubmissions?: (isAllSubmissions: boolean) => void;
  disabled?: boolean;
};

export default function SubmissionSelect({
  exercise,
  submission,
  onChange,
  isAllSubmissions,
  setIsAllSubmissions,
  disabled,
}: SubmissionSelectProps) {
  const { data, error, isLoading } = useSubmissions(exercise);
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

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
        {data
          ?.slice() // create a shallow copy to avoid mutating original data
          .sort((a: Submission, b: Submission) => a.id - b.id)
          .map((sub: Submission) => {
          const contentPreview =
            (sub as TextSubmission)?.text ||
            (sub as ProgrammingSubmission)?.repository_uri ||
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
}
