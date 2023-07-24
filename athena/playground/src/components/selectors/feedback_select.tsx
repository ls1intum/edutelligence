import type { Feedback } from "@/model/feedback";
import type { Mode } from "@/model/mode";

import useSWR from "swr";

import fetcher from "@/helpers/fetcher";
import baseUrl from "@/helpers/base_url";

type FeedbackSelectProps = {
  mode: Mode;
  exercise_id?: number;
  submission_id?: number;
  feedback?: Feedback;
  onChange: (feedback: Feedback) => void;
  isAllFeedback?: boolean;
  setIsAllFeedback?: (isAllFeedback: boolean) => void;
};

export default function FeedbackSelect({
  mode,
  exercise_id,
  submission_id,
  feedback,
  onChange,
  isAllFeedback,
  setIsAllFeedback,
}: FeedbackSelectProps) {
  const apiURL = `${baseUrl}/api/mode/${mode}/${
    exercise_id === undefined
      ? "feedbacks"
      : `exercise/${exercise_id}/feedbacks`
  }`;
  const { data, error, isLoading } = useSWR(apiURL, fetcher);
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  let filteredFeedbacks = data;
  if (submission_id) {
    filteredFeedbacks = filteredFeedbacks.filter(
      (fb: Feedback) => fb.submission_id === submission_id
    );
  }

  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Feedback</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={isAllFeedback ? "all" : feedback?.id || ""}
        onChange={(e) => {
          const value = e.target.value;
          if (value === "all") {
            setIsAllFeedback!(true);
          } else {
            onChange(
              filteredFeedbacks.find(
                (fb: Feedback) => fb.id === parseInt(e.target.value)
              )
            );
            if (setIsAllFeedback) setIsAllFeedback(false);
          }
        }}
      >
        <option value={""} disabled>
          Select a feedback
        </option>
        { isAllFeedback !== undefined &&
          setIsAllFeedback !== undefined && (
          <option
            key="all"
            value="all"
            onClick={() => { setIsAllFeedback(!isAllFeedback)}
          }>
            ✨ All feedback
            </option>
          )}
        {filteredFeedbacks.map((feedback: Feedback) => (
          <option key={feedback.id} value={feedback.id}>
            {feedback.id} ({feedback.credits} credits) {feedback.title || feedback.description || "N/A"}
          </option>
        ))}
      </select>
    </label>
  );
}
