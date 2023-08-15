import { ModuleProvider } from "@/hooks/module_context";
import { ModuleConfiguration } from "../configure_modules";
import { Experiment } from "../define_experiment";
import useBatchModuleExperiment from "@/hooks/batch_module_experiment";

type ConductBatchModuleExperimentProps = {
  experiment: Experiment;
  moduleConfiguration: ModuleConfiguration;
};

function ConductBatchModuleExperiment({ experiment }: ConductBatchModuleExperimentProps) {
  const { state, info } = useBatchModuleExperiment(experiment);

  return (
    <div>
      {info}
      {JSON.stringify(state)}
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
