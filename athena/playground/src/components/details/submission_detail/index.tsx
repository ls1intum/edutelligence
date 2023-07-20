import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import { isProgrammingSubmission, isTextSubmission } from "@/model/submission";
import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";

type SubmissionDetailProps = {
  submission: Submission;
  feedbacks?: Feedback[];
};

export default function SubmissionDetail({
  submission,
  feedbacks,
}: SubmissionDetailProps) {
  if (isProgrammingSubmission(submission)) {
    return (
      <ProgrammingSubmissionDetail
        submission={submission}
        feedbacks={feedbacks}
      />
    );
  } else if (isTextSubmission(submission)) {
    return (
      <TextSubmissionDetail submission={submission} feedbacks={feedbacks} />
    );
  } else {
    return null;
  }
}
