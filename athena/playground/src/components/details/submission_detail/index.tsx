import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";

import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";
import ModelingSubmissionDetail from "@/components/details/submission_detail/modeling";

type SubmissionDetailProps = {
  identifier?: string;
  submission: Submission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  manualRatings?: ManualRating[];
  onManualRatingsChange?: (manualRatings: ManualRating[]) => void;
};

export default function SubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
  manualRatings,
  onManualRatingsChange,
}: SubmissionDetailProps) {

  if (submission.type === "programming") {
    return (
      <ProgrammingSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        manualRatings={manualRatings}
        onManualRatingsChange={onManualRatingsChange}
      />
    );
  } else if (submission.type === "text") {
    return (
      <TextSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        manualRatings={manualRatings}
        onManualRatingsChange={onManualRatingsChange}
      />
    );
  } else if (submission.type === "modeling") {
    return (
      <ModelingSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        manualRatings={manualRatings}
        onManualRatingsChange={onManualRatingsChange}
      />
    );
  } else {
    return null;
  }
}
