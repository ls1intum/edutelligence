import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";

import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";
import ModellingSubmissionDetail from "@/components/details/submission_detail/modelling";

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
  } else if (submission.type === "modelling") {
    return (
      <ModellingSubmissionDetail
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
