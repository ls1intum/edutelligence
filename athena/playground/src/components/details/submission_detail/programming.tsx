import type { ProgrammingSubmission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import CodeView from "@/components/details/code_view";
import FeedbackDetail from "@/components/details/feedback";

type ProgrammingSubmissionDetailProps = {
  submission: ProgrammingSubmission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function ProgrammingSubmissionDetail({
  submission,
  feedbacks,
  onFeedbacksChange,
}: ProgrammingSubmissionDetailProps) {
  return (
    <>
      <CodeView repository_url={submission.repository_url} feedbacks={feedbacks} onFeedbacksChange={onFeedbacksChange}/>
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
