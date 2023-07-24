import type { Mode } from "@/model/mode";
import type { ProgrammingSubmission, Submission, TextSubmission } from "@/model/submission";

import useSWR from "swr";
import fetcher from "@/helpers/fetcher";
import baseUrl from "@/helpers/base_url";

type SubmissionSelectProps = {
  mode: Mode;
  exercise_id?: number;
  submission?: Submission;
  onChange: (submission: Submission) => void;
  isAllSubmissions?: boolean;
  setIsAllSubmissions?: (isAllSubmissions: boolean) => void;
};

export default function SubmissionSelect({
  mode,
  exercise_id,
  submission,
  onChange,
  isAllSubmissions,
  setIsAllSubmissions,
}: SubmissionSelectProps) {
  const apiURL = `${baseUrl}/api/mode/${mode}/${
    exercise_id === undefined
      ? "submissions"
      : `exercise/${exercise_id}/submissions`
  }`;
  const { data, error, isLoading } = useSWR(apiURL, fetcher);
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Submission</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={isAllSubmissions ? "all" : submission?.id || ""}
        onChange={(e) => {
          const value = e.target.value;
          if (value === "all") {
            setIsAllSubmissions!(true);
          } else {
            onChange(
              data.find(
                (sub: Submission) => sub.id === parseInt(e.target.value)
              )
            );
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
        {data.map((sub: Submission) => {
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
}
