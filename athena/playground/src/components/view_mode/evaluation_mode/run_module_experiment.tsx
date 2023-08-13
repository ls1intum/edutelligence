import type { Feedback } from "@/model/feedback";
import type { Submission } from "@/model/submission";
import type { Experiment } from "./define_experiment";

import { useEffect, useId, useState } from "react";

import useRequestFeedbackSuggestions from "@/hooks/athena/request_feedback_suggestions";

import SubmissionDetail from "@/components/details/submission_detail";
import useSendSubmissions from "@/hooks/athena/send_submissions";
import { useSendFeedbacks } from "@/hooks/athena/send_feedbacks";
import useFeedbacks from "@/hooks/playground/feedbacks";
import { AthenaError } from "@/hooks/athena_fetcher";

type RunModuleExperimentProps = {
  experiment: Experiment;
  currentSubmissionIndex: number;
};

export default function RunModuleExperiment({
  experiment,
  currentSubmissionIndex,
}: RunModuleExperimentProps) {
  const id = useId();

  const { data: feedbacks, isLoading: isLoadingFeedbacks } = useFeedbacks();
  const { data: sendSubmissionsData, mutate: sendSubmissions, isLoading: isLoadingSendSubmissions } = useSendSubmissions();
  const { mutate: sendFeedbacks, isLoading: isLoadingSendFeedbacks } = useSendFeedbacks();
  const { mutate: requestFeedbackSuggestions, isLoading: isLoadingFeedbackSuggestions } = useRequestFeedbackSuggestions();
  const [suggestedFeedbacks, setSuggestedFeedbacks] = useState<{ [submissionId: string]: Feedback[] }>({});

  const [areSubmissionsSent, setAreSubmissionsSent] = useState<boolean>(false);
  const [areFeedbacksSent, setAreFeedbacksSent] = useState<boolean>(false);
  const [sendFeedbackItems, setSendFeedbacksItems] = useState<{ submission: Submission; feedbacks: Feedback[] }[] | undefined>(undefined);

  // Send all submissions on mount
  useEffect(() => {
    console.log("useEffect: send submissions")
    if (sendSubmissionsData !== undefined || isLoadingSendSubmissions) {
      return;
    }
    sendSubmissions({
      exercise: experiment.exercise,
      submissions: [
        ...(experiment.experimentSubmissions.trainingSubmissions ?? []),
        ...experiment.experimentSubmissions.evaluationSubmissions,
      ],
    }, {
      onError: (error: AthenaError) => {
        console.error(error);
      },
      onSuccess: () => {
        setAreSubmissionsSent(true);
      },
    });
  }, []);

  // Send feedbacks if submissions are sent and they are loaded
  useEffect(() => {
    console.log("useEffect: send feedbacks")
    const trainingSubmissions = experiment.experimentSubmissions.trainingSubmissions;
    if (trainingSubmissions === undefined) {
      setAreFeedbacksSent(true);
      return;
    }

    if (!areSubmissionsSent || isLoadingFeedbacks || feedbacks === undefined) {
      return
    }

    let items: { submission: Submission; feedbacks: Feedback[] }[] = [];
    trainingSubmissions.forEach((submission) => {
      const submissionFeedbacks = feedbacks.filter((f) => f.submission_id === submission.id);
      if (submissionFeedbacks.length > 0) {
        items.push({ submission, feedbacks: submissionFeedbacks });
      }
    });
    setSendFeedbacksItems(items);
  }, [areSubmissionsSent, isLoadingFeedbacks]);

  // Send feedbacks sequentially
  useEffect(() => {
    console.log("useEffect: send feedbacks items")
    if (sendFeedbackItems === undefined) {
      return;
    }

    if (sendFeedbackItems.length === 0) {
      setAreFeedbacksSent(true);
      return;
    }

    const { submission, feedbacks } = sendFeedbackItems[0];
    sendFeedbacks({
      exercise: experiment.exercise,
      submission,
      feedbacks,
    }, {
      onError: (error: AthenaError) => {
        console.error(error);
      },
      onSuccess: () => {
        setSendFeedbacksItems([...sendFeedbackItems].slice(1));
      }
    });
  }, [sendFeedbackItems]);

  useEffect(() => {
    console.log("useEffect: send feedback suggestions")
    if (!areSubmissionsSent || !areFeedbacksSent || isLoadingFeedbackSuggestions || currentSubmissionIndex < 0) {
      console.log("Not sending feedback suggestions");
      return;
    }

    const submission = experiment.experimentSubmissions.evaluationSubmissions[currentSubmissionIndex];
    if (suggestedFeedbacks[submission.id] === undefined) {
      requestFeedbackSuggestions({
        exercise: experiment.exercise,
        submission,
      }, {
        onSuccess: (response) => {
          setSuggestedFeedbacks((prev) => ({
            ...prev,
            [submission.id]: response.data,
          }));
          console.log("feedback suggestions", response.data);
        },
        onError: (error: AthenaError) => {
          console.error(error);
        },
      });
    }
  }, [areSubmissionsSent, areFeedbacksSent, isLoadingFeedbackSuggestions, currentSubmissionIndex]);

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-4">
      {currentSubmissionIndex >= 0 && experiment.experimentSubmissions.evaluationSubmissions[currentSubmissionIndex] ? (
        <SubmissionDetail
          identifier={id}
          submission={experiment.experimentSubmissions.evaluationSubmissions[currentSubmissionIndex]}
          feedbacks={suggestedFeedbacks[experiment.experimentSubmissions.evaluationSubmissions[currentSubmissionIndex].id] ?? []}
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
