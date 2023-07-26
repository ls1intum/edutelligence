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
  const createNewFeedback = () => {
    const newFeedback: Feedback = {
      id: undefined,
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
        submission={submission}
        feedbacks={feedbacks}
        onFeedbacksChange={onFeedbacksChange}
        createNewFeedback={createNewFeedback}
      />
    );
  } else if (submission.type === "text") {
    return (
      <TextSubmissionDetail
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
