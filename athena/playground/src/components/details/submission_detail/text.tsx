import type { TextSubmission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";

import FileEditor from "@/components/details/editor/file_editor";
import InlineFeedback from "@/components/details/editor/inline_feedback";
import { createFeedbackItemUpdater, getFeedbackReferenceType, createNewFeedback } from "@/model/feedback";
import { createManualRatingItemUpdater } from "@/model/manual_rating";

type TextSubmissionDetailProps = {
  identifier?: string;
  submission: TextSubmission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  manualRatings?: ManualRating[];
  onManualRatingsChange?: (manualRatings: ManualRating[]) => void;
};

export default function TextSubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
  manualRatings,
  onManualRatingsChange,
}: TextSubmissionDetailProps) {
  const unreferencedFeedbacks = feedbacks?.filter(
    (feedback) => getFeedbackReferenceType(feedback) === "unreferenced"
  );
  return (
    <>
      <div className="border border-gray-100 rounded-lg overflow-hidden">
        <FileEditor
          key={`submission-${submission.id}`}
          identifier={identifier}
          content={submission.text}
          autoHeight
          noFileFeedback
          feedbacks={feedbacks}
          onFeedbacksChange={onFeedbacksChange}
          manualRatings={manualRatings}
          onManualRatingsChange={onManualRatingsChange}
          createNewFeedback={() => createNewFeedback(submission)}
        />
      </div>
      {((unreferencedFeedbacks && unreferencedFeedbacks.length > 0) ||
        onFeedbacksChange) && (
        <div className="space-y-2 mt-5">
          <h3 className="ml-2 text-lg font-medium">Unreferenced Feedback</h3>
          {feedbacks?.map(
            (feedback) =>
              getFeedbackReferenceType(feedback) === "unreferenced" && (
                <InlineFeedback
                  key={feedback.id}
                  feedback={feedback}
                  manualRating={manualRatings?.find(
                    (manualRating) => manualRating.feedbackId === feedback.id
                  )}
                  onFeedbackChange={
                    onFeedbacksChange &&
                    createFeedbackItemUpdater(feedback, feedbacks, onFeedbacksChange)
                  }
                  onManualRatingChange={
                    onManualRatingsChange &&
                    createManualRatingItemUpdater(feedback.id, manualRatings, onManualRatingsChange)
                  }
                />
              )
          )}
          {onFeedbacksChange && (
            <button
              className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
              onClick={() =>
                onFeedbacksChange([...(feedbacks ?? []), createNewFeedback(submission)])
              }
            >
              Add feedback
            </button>
          )}
        </div>
      )}
    </>
  );
}
