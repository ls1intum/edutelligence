import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";

type SubmissionDetailProps = {
  identifier?: string;
  submission: Submission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  onFeedbacksChangeEvaluation?: (feedback: Feedback[]) => void;
};

export default function SubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
  onFeedbacksChangeEvaluation,
}: SubmissionDetailProps) {
  if (submission.type === "programming") {
    return (
      <ProgrammingSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        onFeedbacksChangeEvaluation={onFeedbacksChangeEvaluation}
      />
    );
  } else if (submission.type === "text") {
    return (
      <TextSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        onFeedbacksChangeEvaluation={onFeedbacksChangeEvaluation}
      />
    );
  } else {
    return null;
  }
}
