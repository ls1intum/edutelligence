import type { Experiment } from "./define_experiment";

import { useId, useState } from "react";
import SubmissionDetail from "@/components/details/submission_detail";
import useFeedbacks from "@/hooks/playground/feedbacks";

export default function ExperimentSubmissions({
  experiment,
}: {
  experiment: Experiment;
}) {
  const id = useId();
  const [currentIndex, setCurrentSubmissionIndex] = useState(-1);
  const currentSubmission =
    currentIndex >= 0
      ? experiment.experimentSubmissions.testSubmissions[currentIndex]
      : undefined;
  const { data: feedbacks } = useFeedbacks(
    experiment.exercise,
    currentSubmission
  );

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-4">
      <div className="flex flex-row space-x-2 items-center">
        <button
          className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          onClick={() => {
            if (currentIndex <= 0) {
              return;
            }
            setCurrentSubmissionIndex(currentIndex - 1);
          }}
        >
          Previous
        </button>
        <button
          className="bg-primary-500 text-white rounded-md p-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed"
          onClick={() => {
            if (
              currentIndex >=
              experiment.experimentSubmissions.testSubmissions.length - 1
            )
              return;
            setCurrentSubmissionIndex(currentIndex + 1);
          }}
        >
          Next
        </button>
        <div className="flex flex-col">
          <span className="text-gray-500">
            {currentIndex < 0
              ? "No submission selected"
              : `Selected: Submission ${currentIndex + 1} (id: ${currentSubmission?.id})`}
          </span>
          <span className="text-gray-500">
            Progress: ({currentIndex + 1} /{" "}
            {experiment.experimentSubmissions.testSubmissions.length})
          </span>
        </div>
      </div>
      {currentSubmission ? (
        <SubmissionDetail
          identifier={id}
          submission={currentSubmission}
          feedbacks={feedbacks}
        />
      ) : (
        <p className="text-gray-500">
          No submission selected. Please click next to select a submission.
        </p>
      )}
    </div>
  );
}
