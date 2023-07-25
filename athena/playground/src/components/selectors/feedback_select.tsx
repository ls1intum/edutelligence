import type { Feedback } from "@/model/feedback";
import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import useFeedbacks from "@/hooks/playground/feedbacks";

type FeedbackSelectProps = {
  exercise?: Exercise;
  submission?: Submission;
  feedback?: Feedback;
  onChange: (feedback: Feedback) => void;
  isAllFeedback?: boolean;
  setIsAllFeedback?: (isAllFeedback: boolean) => void;
  disabled?: boolean;
};

export default function FeedbackSelect({
  exercise,
  submission,
  feedback,
  onChange,
  isAllFeedback,
  setIsAllFeedback,
  disabled,
}: FeedbackSelectProps) {
  const { data, error, isLoading } = useFeedbacks(exercise, submission)
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;

  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Feedback</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={isAllFeedback ? "all" : feedback?.id || ""}
        disabled={disabled}
        onChange={(e) => {
          const value = e.target.value;
          if (value === "all") {
            setIsAllFeedback!(true);
          } else {
            onChange(data!.find((fb: Feedback) => fb.id === parseInt(e.target.value))!);
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
        {data?.map((feedback: Feedback) => (
          <option key={feedback.id} value={feedback.id}>
            {feedback.id} ({feedback.credits} credits) {feedback.title || feedback.description || "N/A"}
          </option>
        ))}
      </select>
    </label>
  );
}
