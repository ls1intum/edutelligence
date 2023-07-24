import type { TextSubmission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import FeedbackDetail from "@/components/details/feedback";
import FileEditor from "@/components/details/code_view/file_editor";

type TextSubmissionDetailProps = {
  submission: TextSubmission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function TextSubmissionDetail({
  submission,
  feedbacks,
  onFeedbacksChange,
}: TextSubmissionDetailProps) {
  return (
    <>
      <FileEditor content={submission.content} feedbacks={feedbacks} onFeedbacksChange={onFeedbacksChange} />
      {feedbacks && feedbacks.length > 0 && (
        <div className="space-y-1 mt-2">
          {feedbacks.map((feedback) => (
            <FeedbackDetail key={feedback.id} feedback={feedback} />
          ))}
        </div>
      )}
    </>
  );
}
