import { Feedback, formatReference } from "@/model/feedback";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback) => void;
};

export default function InlineFeedback({
  feedback,
  onFeedbackChange,
}: InlineFeedbackProps) {
  return (
    <div className="m-2 border border-gray-300 rounded-lg">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-300 text-xs">
        Suggestion on {formatReference(feedback)}
      </div>
      <div className="flex items-center justify-start">
        <div>Points</div>
        <div>
          <div>Title</div>
          <div>Description</div>
        </div>
      </div>
      <div>Controls</div>
    </div>
  );
}
