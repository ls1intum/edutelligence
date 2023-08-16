import { ModuleProvider } from "@/hooks/module_context";
import { ModuleConfiguration } from "../configure_modules";
import { Experiment } from "../define_experiment";
import useBatchModuleExperiment from "@/hooks/batch_module_experiment";
import ModuleExperimentProgress from "./module_experiment_progress";

type ConductBatchModuleExperimentProps = {
  experiment: Experiment;
  moduleConfiguration: ModuleConfiguration;
};

function ConductBatchModuleExperiment({ experiment }: ConductBatchModuleExperimentProps) {
  const moduleExperiment = useBatchModuleExperiment(experiment);

  return (
    <div className="my-2">
      <ModuleExperimentProgress experiment={experiment} moduleExperiment={moduleExperiment} />
    </div>
  );
}

export default function ConductBatchModuleExperimentWrapped({
  experiment,
  moduleConfiguration,
}: ConductBatchModuleExperimentProps) {
  return (
    <ModuleProvider
      module={moduleConfiguration.moduleAndConfig.module}
      moduleConfig={moduleConfiguration.moduleAndConfig.moduleConfig}
    >
      <ConductBatchModuleExperiment
        experiment={experiment}
        moduleConfiguration={moduleConfiguration}
      />
    </ModuleProvider>
  );
}
