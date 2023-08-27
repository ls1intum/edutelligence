import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import Disclosure from "@/components/disclosure";
import SubmissionDetail from "@/components/details/submission_detail";

type SubmissionListProps = {
  submissions: Submission[];
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
};

export default function SubmissionList({
  submissions,
  feedbacks,
  onFeedbacksChange,
}: SubmissionListProps) {
  let feedbacksBySubmissionId: Record<number, Feedback[]> = {};
  if (feedbacks) {
    feedbacksBySubmissionId = feedbacks.reduce((acc, feedback) => {
      if (!acc[feedback.submission_id]) {
        acc[feedback.submission_id] = [];
      }
      acc[feedback.submission_id].push(feedback);
      return acc;
    }, {} as Record<number, Feedback[]>);
  }
  
  if (submissions.length === 0) {
    return <div className="text-gray-500 text-sm">No submissions</div>;
  }

  return (
    <Disclosure
      title={`${submissions.length} Submission${submissions.length === 1 ? "" : "s"}`}
      className={{ content: "space-y-1" }}
    >
      {submissions.map((submission) => (
        <Disclosure title={`Submission ${submission.id}`} key={submission.id} noContentIndent>
          <SubmissionDetail
            key={submission.id}
            submission={submission}
            feedbacks={feedbacksBySubmissionId[submission.id]}
            onFeedbacksChange={onFeedbacksChange}
          />
        </Disclosure>
      ))}
    </Disclosure>
  );
}
