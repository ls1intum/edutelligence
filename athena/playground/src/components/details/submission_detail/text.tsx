import type { TextSubmission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import Markdown from "@/components/markdown";
import FeedbackDetail from "@/components/details/feedback";
import FileEditor from "@/components/details/code_view/file_editor";

type TextSubmissionDetailProps = {
  submission: TextSubmission;
  feedbacks?: Feedback[];
};

export default function TextSubmissionDetail({
  submission,
  feedbacks,
}: TextSubmissionDetailProps) {
  return (
    <>
      <FileEditor content={submission.content} feedbacks={feedbacks} onFeedbackChange={() => {}} />
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
