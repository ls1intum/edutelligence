import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";

type SubmissionDetailProps = {
  submission: Submission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function SubmissionDetail({
  submission,
  feedbacks,
  onFeedbacksChange,
}: SubmissionDetailProps) {
  if (submission.type === "programming") {
    return (
      <ProgrammingSubmissionDetail
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
      />
    );
  } else if (submission.type === "text") {
    return (
      <TextSubmissionDetail submission={submission} feedbacks={feedbacks} onFeedbacksChange={onFeedbacksChange} />
    );
  } else {
    return null;
  }
}
