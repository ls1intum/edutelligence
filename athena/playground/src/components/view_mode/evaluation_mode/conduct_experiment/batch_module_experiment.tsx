import type { Submission } from "@/model/submission";
import type { Experiment } from "../define_experiment";
import type { ExperimentStep } from "@/hooks/batch_module_experiment";

import React, { useImperativeHandle, useState, ForwardedRef, useEffect } from "react";
import Modal from "react-modal";
import { FullScreenHandle } from "react-full-screen";

import useHealth from "@/hooks/health";
import useBatchModuleExperiment from "@/hooks/batch_module_experiment";
import { ModuleProvider } from "@/hooks/module_context";
import { ExperimentIdentifiersProvider } from "@/hooks/experiment_identifiers_context";
import { ModuleConfiguration } from "../configure_modules";
import ModuleExperimentProgress from "./module_experiment_progress";
import SubmissionDetail from "@/components/details/submission_detail";
import ModuleConfigSelect from "@/components/selectors/module_config_select";

type ConductBatchModuleExperimentProps = {
  experiment: Experiment;
  moduleConfiguration: ModuleConfiguration;
  viewSubmission: Submission;
  didStartExperiment: boolean;
  moduleOrderControl: {
    isFirstModule: boolean;
    isLastModule: boolean;
    onClickPrev: () => void;
    onClickNext: () => void;
  };
  onChangeStep: (step: ExperimentStep) => void;
  fullScreenHandle: FullScreenHandle;
};

export type ConductBatchModuleExperimentHandles = {
  importData: ReturnType<typeof useBatchModuleExperiment>["importData"];
  exportData: ReturnType<typeof useBatchModuleExperiment>["exportData"];
};

// ForwardRef is needed to expose the ref to the parent component
const ConductBatchModuleExperiment = React.forwardRef<
  ConductBatchModuleExperimentHandles,
  ConductBatchModuleExperimentProps
>(
  (
    {
      experiment,
      moduleConfiguration,
      viewSubmission,
      moduleOrderControl,
      didStartExperiment,
      onChangeStep,
      fullScreenHandle,
    }: ConductBatchModuleExperimentProps,
    ref: ForwardedRef<ConductBatchModuleExperimentHandles>
  ) => {
    const { data: health } = useHealth();
    const moduleExperiment = useBatchModuleExperiment(experiment);

    const [showProgress, setShowProgress] = useState(true);
    const [isConfigModalOpen, setConfigModalOpen] = useState(false);

    function handleOpenModal() {
      document.body.style.overflow = "hidden"; // Prevent scrolling
      setConfigModalOpen(true);
    }

    function handleCloseModal() {
      document.body.style.overflow = "unset"; // Restore scrolling
      setConfigModalOpen(false);
    }

    if (didStartExperiment) {
      moduleExperiment.startExperiment();
    }

    useImperativeHandle(ref, () => ({
      importData: moduleExperiment.importData,
      exportData: moduleExperiment.exportData,
    }));

    useEffect(() => {
      onChangeStep(moduleExperiment.data.step);
    }, [moduleExperiment.data.step]);

    return (
      <div>
        <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
          <div className="flex flex-col mb-2">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-lg font-bold">{moduleConfiguration.name}</h4>
              <div className="flex flex-1 justify-end gap-1 mb-1 self-start">
                {moduleExperiment.continueAfterTraining && (
                <button 
                  className="rounded-md p-2 bg-primary-500 hover:bg-primary-600 text-white text-base leading-none"
                  onClick={moduleExperiment.continueAfterTraining}
                  >
                  Start Generating
                </button>
                )}
                <button
                  disabled={moduleOrderControl.isFirstModule}
                  className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
                  onClick={moduleOrderControl.onClickPrev}
                >
                  ←
                </button>
                <button
                  disabled={moduleOrderControl.isLastModule}
                  className="w-8 h-8 rounded-md p-2 bg-gray-100 hover:bg-gray-200 font-bold text-gray-500 hover:text-gray-600 text-base leading-none disabled:text-gray-300 disabled:bg-gray-50 disabled:cursor-not-allowed"
                  onClick={moduleOrderControl.onClickNext}
                >
                  →
                </button>
              </div>
            </div>
            <div className="flex items-center justify-between gap-2">
              <div className="flex flex-wrap gap-1">
                {health?.modules[
                  moduleConfiguration.moduleAndConfig.module.name
                ] ? (
                  <span className="rounded-full bg-green-500 text-white px-2 py-0.5 text-xs">
                    Healthy
                  </span>
                ) : (
                  <span className="rounded-full bg-red-500 text-white px-2 py-0.5 text-xs">
                    Unhealthy
                  </span>
                )}
                {moduleExperiment.data.step === "finished" ? (
                  <span className="rounded-full bg-green-500 text-white px-2 py-0.5 text-xs">
                    Finished
                  </span>
                ) : moduleExperiment.data.step !== undefined ? (
                  <span className="rounded-full bg-yellow-500 text-white px-2 py-0.5 text-xs">
                    {moduleExperiment.continueAfterTraining ?
                      <>Waiting&nbsp;to&nbsp;Continue</>
                    : <>In&nbsp;Progress</>
                    }
                  </span>
                ) : (
                  <span className="rounded-full bg-gray-500 text-white px-2 py-0.5 text-xs">
                    Not&nbsp;Started
                  </span>
                )}
              </div>
              <div className="flex gap-3 items-center text-sm whitespace-nowrap">
                <button
                  className="text-gray-500 hover:text-gray-700"
                  onClick={() => {
                    if (fullScreenHandle.active) {
                      fullScreenHandle.exit();
                    }
                    setConfigModalOpen(true);
                  }}
                >
                  Show&nbsp;Config
                </button>
                <button
                  className="text-gray-500 hover:text-gray-700"
                  onClick={() => {
                    setShowProgress((prev) => !prev);
                  }}
                >
                  {showProgress ? "Hide" : "Show"}&nbsp;Progress
                  <span
                    className="inline-block transform transition-transform duration-200 ml-1"
                    style={{
                      transform: showProgress
                        ? "rotate(90deg)"
                        : "rotate(0deg)",
                    }}
                  >
                    ▶
                  </span>
                </button>
              </div>
            </div>
          </div>
          {showProgress && (
            <div className="my-2">
              <ModuleExperimentProgress
                experiment={experiment}
                moduleExperiment={moduleExperiment}
              />
            </div>
          )}
        </div>
        <div className="my-2 space-y-2">
          {moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
            viewSubmission.id
          ) === undefined && (
            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4 text-sm text-yellow-700 flex flex-col gap-1">
              <span className="font-bold">No feedbacks yet</span>
              <span className="text-sm">
                This submission has not been processed by this module yet.
              </span>
            </div>
          )}
          <SubmissionDetail
            identifier={moduleConfiguration.id}
            submission={viewSubmission}
            feedbacks={
              moduleExperiment.data.submissionsWithFeedbackSuggestions.get(
                viewSubmission.id
              )?.suggestions ?? []
            }
          />
        </div>
        <Modal
          style={{
            overlay: {
              backgroundColor: "rgba(0, 0, 0, 0.8)",
              zIndex: 1000,
            },
          }}
          className="max-w-4xl max-h-[90vh] overflow-y-auto bg-white rounded-lg mx-auto my-12"
          isOpen={isConfigModalOpen}
          onAfterOpen={handleOpenModal}
          onRequestClose={handleCloseModal}
        >
          <div className="p-4">
            <div className="sticky top-0 bg-white border-b border-gray-300 z-10 px-2">
              <div className="flex items-center gap-2">
                <h2 className="text-2xl font-bold py-2">
                  {moduleConfiguration.name}
                </h2>
                <div className="flex flex-wrap gap-1">
                  <span className="rounded-full bg-blue-500 text-white px-2 py-0.5 text-xs">
                    {moduleConfiguration.moduleAndConfig.module.name}
                  </span>
                </div>
                <div className="flex flex-1 justify-end gap-2 mb-1 items-start overscroll-contain">
                  <button
                    className="text-primary-500"
                    onClick={handleCloseModal}
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
            <ModuleConfigSelect
              module={moduleConfiguration.moduleAndConfig.module}
              moduleConfig={moduleConfiguration.moduleAndConfig.moduleConfig}
              disabled
            />
          </div>
        </Modal>
      </div>
    );
  }
);

ConductBatchModuleExperiment.displayName = "ConductBatchModuleExperiment";

function ConductBatchModuleExperimentWrapped(
  props: ConductBatchModuleExperimentProps,
  ref: React.Ref<ConductBatchModuleExperimentHandles>
) {
  return (
    <ExperimentIdentifiersProvider experimentIdentifiers={{
      experimentId: props.experiment.id,
      moduleConfigurationId: props.moduleConfiguration.id,
    }}>
      <ModuleProvider
        module={props.moduleConfiguration.moduleAndConfig.module}
        moduleConfig={props.moduleConfiguration.moduleAndConfig.moduleConfig}
      >
        <ConductBatchModuleExperiment {...props} ref={ref} />
      </ModuleProvider>
    </ExperimentIdentifiersProvider>
  );
}

export default React.forwardRef(ConductBatchModuleExperimentWrapped);
