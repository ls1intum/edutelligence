import type { Feedback } from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";
import type { AutomaticEvaluation } from "@/model/automatic_evaluation";
import type { Experiment } from "@/components/view_mode/evaluation_mode/define_experiment";
import type { ModuleConfiguration } from "@/components/view_mode/evaluation_mode/configure_modules";

import { v4 as uuidv4 } from "uuid";
import { useEffect, useRef, useState } from "react";
import { useSendFeedbacks } from "./athena/send_feedbacks";
import { useSendResults } from "./athena/send_results";
import useRequestSubmissionSelection from "./athena/request_submission_selection";
import useRequestFeedbackSuggestions from "./athena/request_feedback_suggestions";
import useSendSubmissions from "./athena/send_submissions";
import useRequestEvaluation from "./athena/request_evaluation";
import { useExperimentIdentifiersSetRunId } from "./experiment_identifiers_context";

export type ExperimentStep =
  | "notStarted"
  | "sendingSubmissions"
  | "sendingTrainingFeedbacks"
  | "generatingGradedFeedbackSuggestions"
  | "finished";

export type BatchModuleExperimentState = {
  // Run ID
  runId: string;
  // The current step of the experiment
  step: ExperimentStep;
  // Submissions that have been sent to Athena
  didSendSubmissions: boolean;
  // Tutor feedbacks for training submissions that have been sent to Athena
  sentTrainingSubmissions: number[];
  // Feedback suggestions for evaluation submissions that have been generated by Athena
  // SubmissionId -> { suggestions: Feedback[]; meta: any;} where meta is the metadata of the request
  submissionsWithFeedbackSuggestions: Map<
    number,
    { suggestions: Feedback[]; meta: any }
  >;
};

export default function useBatchModuleExperiment(experiment: Experiment, moduleConfiguration: ModuleConfiguration) {
  // State of the module experiment
  const [data, setData] = useState<BatchModuleExperimentState>({
    runId: uuidv4(),
    step: "notStarted", // Not started
    didSendSubmissions: false,
    sentTrainingSubmissions: [],
    submissionsWithFeedbackSuggestions: new Map(),
  });

  // Stores annotations for manual evaluation
  const [submissionsWithManualRatings, setSubmissionsWithManualRatings] = useState<
    Map<number, ManualRating[]>
  >(new Map());

  // Stores automatic evaluation of submissions
  const [submissionsWithAutomaticEvaluation, setSubmissionsWithAutomaticEvaluation] = useState<
    Map<number, AutomaticEvaluation> | undefined
  >(undefined);
  const { mutate: sendResultsMutate } = useSendResults();

  const [processingStep, setProcessingStep] = useState<
    ExperimentStep | undefined
  >(undefined);
  const isMounted = useRef(true);
  const setContextRunId = useExperimentIdentifiersSetRunId();

  const startExperiment = () => {
    // Skip if the experiment has already started
    if (data.step !== "notStarted") {
      return;
    }

    setData((prevState) => ({
      ...prevState,
      step: "sendingSubmissions",
    }));
  };


  const analyseData = async (results: any) => {
    const exercise = experiment.exercise
    const submissions = experiment.evaluationSubmissions
    const submissionIds = new Set(submissions.map(submission => submission.id));
    const tutor_feedbacks :any[]= [];
    for (const feedback of experiment.tutorFeedbacks) {
      if (submissionIds.has(feedback.submission_id)) {
        tutor_feedbacks.push(feedback);
      }
    }
  
    return new Promise((resolve, reject) => {
      sendResultsMutate(
        { exercise, tutor_feedbacks, results },
        {
          onSuccess: (response) => {
            // const newWindow = window.open("", "_blank", "width=900,height=900");
            const htmlContent = response[0].data;
  
            const width = 800;
            const height = 600;
            const left = (window.innerWidth - width) / 2;
            const top = (window.innerHeight - height) / 2;
            
            const newWindow = window.open('', '', `width=${width},height=${height},left=${left},top=${top}`);
            newWindow!.document.open();
            newWindow!.document.write(htmlContent);
            newWindow!.document.close();
  
            console.log("Data analysis sent successfully!");
            resolve(results); // Resolve the promise with results
          },
          onError: (error) => {
            console.error("Error sending data analysis to the backend:", error);
            reject(error); // Reject the promise with the error
          },
        }
      );
    });
  };

  const getResults = () => {
    return {
      results: {
        type: "results",
        runId: data.runId,
        experimentId: experiment.id,
        moduleConfigurationId: moduleConfiguration.id,
        step: data.step,
        didSendSubmissions: data.didSendSubmissions,
        sentTrainingSubmissions: data.sentTrainingSubmissions,
        submissionsWithFeedbackSuggestions: Object.fromEntries(
          Array.from(data.submissionsWithFeedbackSuggestions.entries()).map(([key, value]) => [
            key,
            { suggestions: value.suggestions }, // Exclude `meta` here
          ])
        ),
      },
    };}
  
  const exportData = () => {
    return { 
      results: {
        type: "results",
        runId: data.runId,
        experimentId: experiment.id,
        moduleConfigurationId: moduleConfiguration.id,
        step: data.step,
        didSendSubmissions: data.didSendSubmissions,
        sentTrainingSubmissions: data.sentTrainingSubmissions,
        submissionsWithFeedbackSuggestions: Object.fromEntries(
          data.submissionsWithFeedbackSuggestions
        ),
      },
      ...(
        submissionsWithManualRatings.size > 0 ? {
          manualRatings: {
            type: "manualRatings",
            runId: data.runId,
            experimentId: experiment.id,
            moduleConfigurationId: moduleConfiguration.id,
            submissionsWithManualRatings: Object.fromEntries(
              submissionsWithManualRatings
            ),
          },
        } : {}
      ),
      ...(
        submissionsWithAutomaticEvaluation && submissionsWithAutomaticEvaluation.size > 0 ? {
          automaticEvaluation: {
            type: "automaticEvaluation",
            runId: data.runId,
            experimentId: experiment.id,
            moduleConfigurationId: moduleConfiguration.id,
            submissionsWithAutomaticEvaluation: Object.fromEntries(
              submissionsWithAutomaticEvaluation
            ),
          },
        } : {}
      ),
    };
  };

  const importData = (importedData: any) => {
    if (importedData.type === "results") {
      if (importedData.runId === undefined ||
        importedData.step === undefined ||
        importedData.didSendSubmissions === undefined ||
        importedData.sentTrainingSubmissions === undefined ||
        importedData.submissionsWithFeedbackSuggestions === undefined) {
        throw new Error("Invalid results data");
      }

      setProcessingStep(undefined);
      setData(() => ({
        runId: importedData.runId,
        step: importedData.step,
        didSendSubmissions: importedData.didSendSubmissions,
        sentTrainingSubmissions: importedData.sentTrainingSubmissions,
        submissionsWithFeedbackSuggestions: new Map(
          Object.entries(importedData.submissionsWithFeedbackSuggestions).map(
            ([key, value]) => [Number(key), value as any]
          )
        ),
      }));
      return;
    } else if (importedData.type === "manualRatings") {
      // Relies on the fact that the manual ratings have to be imported after the results
      if (importedData.runId !== data.runId) {
        throw new Error("Run ID does not match, have you imported the results first?");
      }
      if (importedData.submissionsWithManualRatings === undefined) {
        throw new Error("Invalid manual ratings data");
      }
      setSubmissionsWithManualRatings(() => new Map(
        Object.entries(importedData.submissionsWithManualRatings).map(
          ([key, value]) => [Number(key), value as any]
        )
      ));
      return;
    } else if (importedData.type === "automaticEvaluation") {
      // Relies on the fact that the automatic evaluations have to be imported after the results
      if (importedData.runId !== data.runId) {
        throw new Error("Run ID does not match, have you imported the results first?");
      }
      if (importedData.submissionsWithAutomaticEvaluation === undefined) {
        throw new Error("Invalid automatic evaluation data");
      }
      setSubmissionsWithAutomaticEvaluation(() => new Map(
        Object.entries(importedData.submissionsWithAutomaticEvaluation).map(
          ([key, value]) => [Number(key), value as any]
        )
      ));
      return;
    }

    throw new Error("Unknown import data type");
  };

  const getManualRatingsSetter = (submissionId: number) => (manualRatings: ManualRating[]) => {
    setSubmissionsWithManualRatings((prevState) => {
      const newMap = new Map(prevState);
      newMap.set(submissionId, manualRatings);
      return newMap;
    });
  };

  const continueAfterTraining = (data.step === "sendingTrainingFeedbacks" && data.sentTrainingSubmissions.length === experiment.trainingSubmissions?.length) ? (() => {
    setData((prevState) => ({
      ...prevState,
      step: "generatingGradedFeedbackSuggestions",
    }));
  }) : undefined;

  const continueWithAutomaticEvaluation = (data.step === "finished" && submissionsWithAutomaticEvaluation === undefined) ? (() => {
    setSubmissionsWithAutomaticEvaluation((prevState) => new Map(prevState));
    stepAutomaticEvaluation();
  }) : undefined;

  // Module requests
  // By default useMutation does not retry, but we want to retry a few times to not get stuck
  // If we still get stuck we can just `Export` -> `Cancel Experiment` -> `Import` again to continue for now
  const sendSubmissions = useSendSubmissions({ retry: 3 });
  const sendFeedbacks = useSendFeedbacks({ retry: 3 });
  const requestSubmissionSelection = useRequestSubmissionSelection({ retry: 3 });
  const requestFeedbackSuggestions = useRequestFeedbackSuggestions({ retry: 3 });
  const requestEvaluation = useRequestEvaluation({ retry: 3 });
  const sendResult = useSendResults({ retry: 3 });
  // 1. Send submissions to Athena
  const stepSendSubmissions = () => {
    setProcessingStep("sendingSubmissions");
    console.log("Sending submissions to Athena...");
    sendSubmissions.mutate(
      {
        exercise: experiment.exercise,
        submissions: [
          ...(experiment.trainingSubmissions ?? []),
          ...experiment.evaluationSubmissions,
        ],
      },
      {
        onSuccess: () => {
          if (!isMounted.current) {
            return;
          }

          console.log("Sending submissions done!");
          setData((prevState) => ({
            ...prevState,
            step: "sendingTrainingFeedbacks", // next step
            didSendSubmissions: true,
          }));
        },
        onError: (error) => {
          console.error("Error while sending submissions to Athena:", error);
          // TODO: Recover?
        },
      }
    );
  };

  // 2. Send tutor feedbacks for training submissions to Athena
  const stepSendTrainingFeedbacks = async () => {
    setProcessingStep("sendingTrainingFeedbacks");
    // Skip if there are no training submissions
    if (!experiment.trainingSubmissions) {
      console.log("No training submissions, skipping");
      setData((prevState) => ({
        ...prevState,
        step: "generatingGradedFeedbackSuggestions",
      }));
      return;
    }

    console.log("Sending training feedbacks to Athena...");

    const submissionsToSend = experiment.trainingSubmissions.filter(
      (submission) => !data.sentTrainingSubmissions.includes(submission.id)
    );

    let num = 0;
    for (const submission of submissionsToSend) {
      num += 1;
      const submissionFeedbacks = experiment.tutorFeedbacks.filter(
        (feedback) => feedback.submission_id === submission?.id
      );
      
      console.log(
        `Sending training feedbacks to Athena... (${num}/${submissionsToSend.length})`
      );

      try {  
        if (submissionFeedbacks.length > 0) {
          await sendFeedbacks.mutateAsync({
            exercise: experiment.exercise,
            submission,
            feedbacks: submissionFeedbacks,
          });
          if (!isMounted.current) {
            return;
          }
        }

        setData((prevState) => ({
          ...prevState,
          sentTrainingSubmissions: [
            ...prevState.sentTrainingSubmissions,
            submission.id,
          ],
        }));
      } catch (error) {
        console.error(
          `Sending training feedbacks for submission ${submission.id} failed with error:`,
          error
        );
      }
    }

    console.log("Sending training feedbacks done waiting to continue...");
  };

  // 3. Generate feedback suggestions
  const stepGenerateGradedFeedbackSuggestions = async () => {
    setProcessingStep("generatingGradedFeedbackSuggestions");
    console.log("Generating feedback suggestions...");

    let remainingSubmissions = experiment.evaluationSubmissions.filter(
      (submission) =>
        !data.submissionsWithFeedbackSuggestions.has(submission.id)
    );

    while (remainingSubmissions.length > 0) {
      const infoPrefix = `Generating feedback suggestions... (${
        experiment.evaluationSubmissions.length -
        remainingSubmissions.length +
        1
      }/${experiment.evaluationSubmissions.length})`;

      console.log(`${infoPrefix} - Requesting feedback suggestions...`);

      let submissionIndex = -1;
      try {
        const response = await requestSubmissionSelection.mutateAsync({
          exercise: experiment.exercise,
          submissions: remainingSubmissions,
        });
        if (!isMounted.current) {
          return;
        }

        console.log("Received submission selection:", response.data);

        if (response.data !== -1) {
          submissionIndex = remainingSubmissions.findIndex(
            (submission) => submission.id === response.data
          );
        }
      } catch (error) {
        console.error("Error while requesting submission selection:", error);
      }

      if (submissionIndex === -1) {
        // Select random submission
        submissionIndex = Math.floor(
          Math.random() * remainingSubmissions.length
        );
      }

      const submission = remainingSubmissions[submissionIndex];
      remainingSubmissions = [
        ...remainingSubmissions.slice(0, submissionIndex),
        ...remainingSubmissions.slice(submissionIndex + 1),
      ];

      console.log(
        `${infoPrefix} - Requesting graded feedback suggestions for submission ${submission.id}...`
      );

      try {
        const response = await requestFeedbackSuggestions.mutateAsync({
          exercise: experiment.exercise,
          submission,
          is_graded: true
        });
        if (!isMounted.current) {
          return;
        }

        console.log("Received feedback suggestions:", response.data);
        setData((prevState) => ({
          ...prevState,
          submissionsWithFeedbackSuggestions: new Map(
            prevState.submissionsWithFeedbackSuggestions.set(submission.id, {
              suggestions: response.data,
              meta: response.meta,
            })
          ),
        }));
      } catch (error) {
        console.error(
          `Error while generating feedback suggestions for submission ${submission.id}:`,
          error
        );
      }
    }

    setData((prevState) => ({
      ...prevState,
      step: "finished", // Automatic evaluation is done separately
    }));
  };

  // 4. Automatic evaluation (after results are 'finished')
  const stepAutomaticEvaluation = async () => {
    setProcessingStep("finished");

    console.log("Running automatic evaluation...");

    let remainingSubmissions = experiment.evaluationSubmissions.filter(
      (submission) => !submissionsWithAutomaticEvaluation?.has(submission.id)
    );
    
    let num = 0;
    for (const submission of remainingSubmissions) {
      num += 1;
      console.log(
        `Evaluating... (${num}/${
          remainingSubmissions.length
        })`
      );

      const predictedFeedbacks = data.submissionsWithFeedbackSuggestions.get(
        submission.id
      )?.suggestions ?? [];

      try {
        const responses = await requestEvaluation.mutateAsync({
          exercise: experiment.exercise,
          submission,
          trueFeedbacks: experiment.tutorFeedbacks.filter(
            (feedback) => feedback.submission_id === submission.id
          ),
          predictedFeedbacks: predictedFeedbacks,
        });
        if (!isMounted.current) {
          return;
        }

        const data = Object.fromEntries(
          responses.map((response) => [response.module_name, response.data])
        );

        console.log(`Received evaluation for submission ${submission.id}:`, data);

        setSubmissionsWithAutomaticEvaluation((prevState) => {
          const newMap = new Map(prevState);
          newMap.set(submission.id, data);
          return newMap;
        });
      } catch (error) {
        console.error(
          `Error while evaluating submission ${submission.id}:`,
          error
        );
      }
    }
  };

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
    };
  }, []);

  useEffect(() => {
    setContextRunId(data.runId);
  }, [data.runId])

  useEffect(() => {
    if (experiment.executionMode !== "batch") {
      console.error("Using useBatchModuleExperiment in non-batch experiment!");
      return;
    }

    console.log("Step changed");
    if (
      data.step === "sendingSubmissions" &&
      processingStep !== "sendingSubmissions"
    ) {
      stepSendSubmissions();
    } else if (
      data.step === "sendingTrainingFeedbacks" &&
      processingStep !== "sendingTrainingFeedbacks"
    ) {
      stepSendTrainingFeedbacks();
    } else if (
      data.step === "generatingGradedFeedbackSuggestions" &&
      processingStep !== "generatingGradedFeedbackSuggestions"
    ) {
      stepGenerateGradedFeedbackSuggestions();
    } 
    // Automatic evaluation is triggered manually
  }, [data.step]);

  return {
    data,
    submissionsWithManualRatings,
    submissionsWithAutomaticEvaluation,
    getManualRatingsSetter,
    startExperiment,
    continueAfterTraining,
    continueWithAutomaticEvaluation,
    exportData,
    importData,
    analyseData,
    getResults,
    moduleRequests: {
      sendSubmissions,
      sendFeedbacks,
      requestSubmissionSelection,
      requestFeedbackSuggestions,
      requestEvaluation,
    },
  };
}
