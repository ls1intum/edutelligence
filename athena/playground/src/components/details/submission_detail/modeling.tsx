import React, { useEffect, useRef, useState } from "react";
import type { UMLElementType, UMLRelationshipType } from "@ls1intum/apollon";

import type { ModelingSubmission } from "@/model/submission";
import type { Feedback, ModelingFeedback } from "@/model/feedback";
import {
  createFeedbackItemUpdater,
  createNewFeedback,
  getFeedbackReferenceType,
} from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";
import { createManualRatingItemUpdater } from "@/model/manual_rating";

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
  feedbacks = [],
  onFeedbacksChange,
  manualRatings = [],
  onManualRatingsChange,
}: ModelingSubmissionDetailProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [editor, setEditor] = useState<any>();

  // Initialize Apollon editor once
  useEffect(() => {
    const { ApollonEditor } = require("@ls1intum/apollon");

    if (!editorRef.current) return;

    const modelObject = JSON.parse(submission.model);

    const newEditor = new ApollonEditor(editorRef.current, {
      model: modelObject,
      readonly: true,
      mode: "Assessment",
      scale: 0.8,
    });

    setEditor(newEditor);
    
  }, [submission]);

  // Update assessments when feedbacks change
  useEffect(() => {
  if (!editor) return;

  const { addOrUpdateAssessment } = require("@ls1intum/apollon");
  const modelObject = JSON.parse(submission.model);

  const referencedFeedbacks = feedbacks.filter(
    (f) => getFeedbackReferenceType(f) === "referenced"
  );

  referencedFeedbacks.forEach((feedback) => {
    const modelingFeedback = feedback as ModelingFeedback;
    const [referenceType, referenceId] =
      modelingFeedback.reference?.split(":") ?? [];

    addOrUpdateAssessment(modelObject, {
      modelElementId: referenceId,
      elementType: referenceType as UMLElementType | UMLRelationshipType,
      score: modelingFeedback.credits,
      feedback: modelingFeedback.description,
    });
  });

  (async () => {
    const renderDone = editor.nextRender;
    editor.model = modelObject;
    await renderDone;
  })();
}, [feedbacks, submission, editor]);

  // Filter unreferenced feedbacks once
  const unreferencedFeedbacks = feedbacks.filter(
    (f) => getFeedbackReferenceType(f) === "unreferenced"
  );

  return (
    <>
      <div className="border border-gray-100 rounded-lg overflow-hidden">
        <div key={identifier} ref={editorRef} style={{ height: 400 }} />
      </div>
      {(unreferencedFeedbacks.length > 0 || onFeedbacksChange) && (
        <div className="space-y-2 mt-5">
          <h3 className="ml-2 text-lg font-medium">Unreferenced Feedback</h3>

          {unreferencedFeedbacks.map((feedback) => (
            <InlineFeedback
              key={feedback.id}
              feedback={feedback}
              manualRating={manualRatings.find(
                (mr) => mr.feedbackId === feedback.id
              )}
              onFeedbackChange={
                onFeedbacksChange &&
                createFeedbackItemUpdater(feedback, feedbacks, onFeedbacksChange)
              }
              onManualRatingChange={
                onManualRatingsChange &&
                createManualRatingItemUpdater(
                  feedback.id,
                  manualRatings,
                  onManualRatingsChange
                )
              }
            />
          ))}

          {onFeedbacksChange && (
            <button
              className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
              onClick={() =>
                onFeedbacksChange([
                  ...feedbacks,
                  createNewFeedback(submission),
                ])
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
