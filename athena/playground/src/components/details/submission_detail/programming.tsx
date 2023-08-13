import type { ProgrammingSubmission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import CodeEditor from "@/components/details/editor/code_editor";
import InlineFeedback from "@/components/details/editor/inline_feedback";
import { getOnFeedbackChange, getFeedbackReferenceType, createNewFeedback } from "@/model/feedback";

type ProgrammingSubmissionDetailProps = {
  identifier?: string;
  submission: ProgrammingSubmission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function ProgrammingSubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
}: ProgrammingSubmissionDetailProps) {
  const unreferencedFeedbacks = feedbacks?.filter((feedback) => getFeedbackReferenceType(feedback) === "unreferenced");
  return (
    <>
      <CodeEditor
        key={identifier ? `${identifier}-${submission.id}` : submission.id}
        identifier={identifier}
        repositoryUrl={submission.repository_url}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        createNewFeedback={() => createNewFeedback(submission)}
      />
      {((unreferencedFeedbacks && unreferencedFeedbacks.length > 0) || onFeedbacksChange) && (
        <div className="space-y-2 mt-5">
          <h3 className="ml-2 text-lg font-medium">Unreferenced Feedback</h3>
          {feedbacks?.map((feedback) => (
            getFeedbackReferenceType(feedback) === "unreferenced" && (
            <InlineFeedback
              key={feedback.id}
              feedback={feedback}
              onFeedbackChange={
                onFeedbacksChange &&
                getOnFeedbackChange(feedback, feedbacks, onFeedbacksChange)
              }
            />)
          ))}
          {onFeedbacksChange && (
            <button
              className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
              onClick={() => onFeedbacksChange([...(feedbacks ?? []), createNewFeedback(submission)])}
            >
              Add feedback
            </button>
          )}
        </div>
      )}
    </>
  );
}
