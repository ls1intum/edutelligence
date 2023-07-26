import type { TextSubmission } from "@/model/submission";
import { getOnFeedbackChange, type Feedback, getFeedbackReferenceType } from "@/model/feedback";

import FileEditor from "@/components/details/editor/file_editor";
import InlineFeedback from "@/components/details/editor/inline_feedback";

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
  const unreferencedFeedbacks = feedbacks?.filter((feedback) => getFeedbackReferenceType(feedback) === "unreferenced");
  return (
    <>
      <FileEditor content={submission.content} feedbacks={feedbacks} onFeedbacksChange={onFeedbacksChange} />
      {((unreferencedFeedbacks && unreferencedFeedbacks.length > 0) || onFeedbacksChange) && (
        <div className="space-y-2 mt-5">
          <h3 className="ml-2 text-lg font-medium">Unreferenced Feedback</h3>
          {feedbacks?.map((feedback, index) => (
            getFeedbackReferenceType(feedback) === "unreferenced" && (
            <InlineFeedback
              key={feedback.id}
              feedback={feedback}
              onFeedbackChange={
                onFeedbacksChange &&
                getOnFeedbackChange(feedbacks, index, onFeedbacksChange)
              }
            />)
          ))}
          {onFeedbacksChange && (
            <button
              className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
              onClick={() => {
                console.log("TODO: Add feedback");
              }}
            >
              Add feedback
            </button>
          )}
        </div>
      )}
    </>
  );
}
