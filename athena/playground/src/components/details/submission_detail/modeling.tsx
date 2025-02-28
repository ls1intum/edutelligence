import React, {useEffect, useRef, useState}  from 'react';

import type {ModelingSubmission} from "@/model/submission";
import type {Feedback} from "@/model/feedback";
import {createFeedbackItemUpdater, createNewFeedback, getFeedbackReferenceType} from "@/model/feedback";
import type {ManualRating} from "@/model/manual_rating";
import {createManualRatingItemUpdater} from "@/model/manual_rating";

import InlineFeedback from "@/components/details/editor/inline_feedback";


type ModelingSubmissionDetailProps = {
  identifier?: string;
  submission: ModelingSubmission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  manualRatings?: ManualRating[];
  onManualRatingsChange?: (manualRatings: ManualRating[]) => void;
};

export default function ModelingSubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
  manualRatings,
  onManualRatingsChange,
}: ModelingSubmissionDetailProps) {
  const unreferencedFeedbacks = feedbacks?.filter(
    (feedback) => getFeedbackReferenceType(feedback) === "unreferenced"
  );

  const editorRef = useRef<HTMLDivElement>(null);

  const [editor, setEditor] = useState<any>();

  useEffect(() => {

    const Apollon = require("@ls1intum/apollon");

    if (!editorRef?.current) {
      return;
    }

    setEditor(new Apollon.ApollonEditor(editorRef.current!, {
      model: JSON.parse(submission.model),
      readonly: true,
      scale: 0.8
    }));

  }, [editorRef, submission]);

  return (
    <>
      <div className="border border-gray-100 rounded-lg overflow-hidden">
        <div key={identifier} ref={editorRef} style={{height: 400}} />
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
