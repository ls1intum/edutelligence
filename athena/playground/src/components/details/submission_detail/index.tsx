import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import TextSubmissionDetail from "./text";
import ProgrammingSubmissionDetail from "./programming";

type SubmissionDetailProps = {
  identifier?: string;
  submission: Submission;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function SubmissionDetail({
  identifier,
  submission,
  feedbacks,
  onFeedbacksChange,
}: SubmissionDetailProps) {
  const createNewFeedback = () => {
    const newFeedback: Feedback = {
      id: Date.now(), // Good enough for the playground
      credits: 0,
      title: "",
      description: "",
      type: submission.type,
      exercise_id: submission.exercise_id,
      submission_id: submission.id,
      is_new: true,
      meta: {},
    };
    return newFeedback;
  };

  if (submission.type === "programming") {
    return (
      <ProgrammingSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        createNewFeedback={createNewFeedback}
      />
    );
  } else if (submission.type === "text") {
    return (
      <TextSubmissionDetail
        identifier={identifier}
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        createNewFeedback={createNewFeedback}
      />
    );
  } else {
    return null;
  }
}
