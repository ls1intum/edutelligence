import { Exercise } from "@/model/exercise";
import { Mode } from "@/model/mode";
import Feedback from "@/model/feedback";

import Disclosure from "@/components/disclosure";
import SubmissionDetail from "@/components/details/submission_detail";

import { useSubmissions } from "@/helpers/client/get_data";

type SubmissionListProps = {
  exercise: Exercise;
  mode: Mode;
  feedbacks?: Feedback[];
};

export default function SubmissionList({
  exercise,
  mode,
  feedbacks,
}: SubmissionListProps) {
  const {
    submissions,
    isLoading: isLoadingSubmissions,
    error: submissionsError,
  } = useSubmissions(mode, exercise);

  if (submissions) {
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
        title={`${submissions.length} Submission${
          submissions.length === 1 ? "" : "s"
        }`}
        className={{ content: "space-y-1" }}
      >
        {submissions.map((submission) => (
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
  } else if (submissionsError) {
    return <div className="text-gray-500 text-sm">Failed to load submissions</div>;
  } else if (isLoadingSubmissions) {
    return <div className="text-gray-500 text-sm">Loading submissions...</div>;
  } else {
    return null;
  }
}
