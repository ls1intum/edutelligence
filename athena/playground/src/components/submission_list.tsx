import type { Exercise } from "@/model/exercise";
import type { Feedback } from "@/model/feedback";

import useSubmissions from "@/hooks/playground/submissions";

import Disclosure from "@/components/disclosure";
import SubmissionDetail from "@/components/details/submission_detail";

type SubmissionListProps = {
  exercise: Exercise;
  feedbacks?: Feedback[];
};

export default function SubmissionList({ exercise, feedbacks }: SubmissionListProps) {
  const { data, isLoading, error } = useSubmissions(exercise);

  if (data) {
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

    return (
      <Disclosure
        title={`${data.length} Submission${
          data.length === 1 ? "" : "s"
        }`}
        className={{ content: "space-y-1" }}
      >
        {data.map((submission) => (
          <Disclosure title={`Submission ${submission.id}`} key={submission.id}>
            <SubmissionDetail
              key={submission.id}
              submission={submission}
              feedbacks={feedbacksBySubmissionId[submission.id]}
            />
          </Disclosure>
        ))}
      </Disclosure>
    );
  } else if (error) {
    return <div className="text-gray-500 text-sm">Failed to load submissions</div>;
  } else if (isLoading) {
    return <div className="text-gray-500 text-sm">Loading submissions...</div>;
  } else {
    return null;
  }
}
