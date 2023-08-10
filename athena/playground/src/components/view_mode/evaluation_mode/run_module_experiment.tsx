import type { Feedback } from "@/model/feedback";
import type { Submission } from "@/model/submission";
import type { Experiment } from "./define_experiment";

import { useEffect, useId, useState } from "react";
import { Allotment } from "allotment";

import { useBaseInfo } from "@/hooks/base_info_context";
import useRequestSubmissionSelection from "@/hooks/athena/request_submission_selection";
import useRequestFeedbackSuggestions from "@/hooks/athena/request_feedback_suggestions";

import SubmissionDetail from "@/components/details/submission_detail";
import ExerciseDetail from "@/components/details/exercise_detail";
import useSendSubmissions from "@/hooks/athena/send_submissions";
import { ModuleConfiguration } from "./configure_modules";

type RunModuleExperimentProps = {
  experiment: Experiment;
  moduleConfiguration: ModuleConfiguration;
};

export default function RunModuleExperiment({
  experiment,
  moduleConfiguration,
}: RunModuleExperimentProps) {
  const id = useId();
  const [currentIndex, setCurrentSubmissionIndex] = useState(-1);

  const { mutate: sendSubmissions, isLoading: isLoadingSendSubmissions } =
    useSendSubmissions();
  const { mutate: selectSubmission, isLoading: isLoadingSubmissionSelection } =
    useRequestSubmissionSelection();
  const {
    mutate: requestFeedbackSuggestions,
    isLoading: isLoadingFeedbackSuggestions,
  } = useRequestFeedbackSuggestions();
  const [submissionsAndFeedbacks, setSubmissionsAndFeedbacks] = useState<
    { submission: Submission; feedbacks: Feedback[] }[]
  >([]);

  useEffect(() => {
    sendSubmissions({
      exercise: experiment.exercise,
      submissions: [
        ...(experiment.experimentSubmissions.trainingSubmissions ?? []),
        ...experiment.experimentSubmissions.evaluationSubmissions,
      ],
    });
  }, []);

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-4">
      <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
        <div className="flex items-center gap-2">
          <h4 className="text-lg font-bold">{moduleConfiguration.name}</h4>
        </div>
      </div>

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
            const nextIndex = currentIndex + 1;
            if (currentIndex >= submissionsAndFeedbacks.length - 1) {
              if (isLoadingSubmissionSelection) {
                return;
              } else if (
                submissionsAndFeedbacks.length <
                experiment.experimentSubmissions.evaluationSubmissions.length
              ) {
                const submissionsToSelectFrom =
                  experiment.experimentSubmissions.evaluationSubmissions.filter(
                    (submission) => {
                      return !submissionsAndFeedbacks.some(
                        (submissionAndFeedback) => {
                          return (
                            submissionAndFeedback.submission.id ===
                            submission.id
                          );
                        }
                      );
                    }
                  );
                selectSubmission(
                  {
                    exercise: experiment.exercise,
                    submissions: submissionsToSelectFrom,
                  },
                  {
                    onSuccess: (reponse) => {
                      const { data: submissionId } = reponse as {
                        data: number;
                      };
                      const submission = submissionsToSelectFrom.find(
                        (submission) => submission.id === submissionId
                      );
                      if (!submission) {
                        throw new Error("Failed to find submission");
                      }
                      requestFeedbackSuggestions(
                        { exercise: experiment.exercise, submission },
                        {
                          onSuccess: (response) => {
                            const { data: feedbacks } = response as {
                              data: Feedback[];
                            };
                            setSubmissionsAndFeedbacks([
                              ...submissionsAndFeedbacks,
                              { submission, feedbacks },
                            ]);
                            setCurrentSubmissionIndex(nextIndex);
                          },
                        }
                      );
                    },
                  }
                );
              }
            } else {
              setCurrentSubmissionIndex(nextIndex);
            }
          }}
        >
          Next
        </button>
        <div className="flex flex-col">
          <span className="text-gray-500">
            {currentIndex < 0
              ? "No submission selected"
              : `Selected: Submission ${currentIndex + 1} (id: ${
                  submissionsAndFeedbacks[currentIndex]?.submission?.id
                })`}
          </span>
          <span className="text-gray-500">
            Progress: ({currentIndex + 1} /{" "}
            {experiment.experimentSubmissions.evaluationSubmissions.length})
          </span>
        </div>
      </div>
      {submissionsAndFeedbacks[currentIndex]?.submission ? (
        <SubmissionDetail
          identifier={id}
          submission={submissionsAndFeedbacks[currentIndex]?.submission}
          feedbacks={submissionsAndFeedbacks[currentIndex]?.feedbacks}
        />
      ) : (
        <p className="text-gray-500">
          No submission selected. Please click next to select a submission.
        </p>
      )}
      {/* 4. Assessment */}
      {/* 5. Send feedback */}
      {/* Go to 2. */}
      {/* <SubmissionDetail submission={selectedSubmission} feedbacks={} /> */}
    </div>
  );
}
