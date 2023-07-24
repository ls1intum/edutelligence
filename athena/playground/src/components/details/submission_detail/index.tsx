import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import { isProgrammingSubmission, isTextSubmission } from "@/model/submission";
import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";
import { IRange } from "monaco-editor";

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
  if (isProgrammingSubmission(submission)) {
    return (
      <ProgrammingSubmissionDetail
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
      />
    );
  } else if (isTextSubmission(submission)) {
    return (
      <TextSubmissionDetail submission={submission} feedbacks={feedbacks} onFeedbacksChange={onFeedbacksChange} />
    );
  } else {
    return null;
  }
}
