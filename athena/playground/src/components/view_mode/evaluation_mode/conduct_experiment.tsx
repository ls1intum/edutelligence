import ModuleSelectAndConfig from "../module_requests/module_select_and_config";
import { Experiment } from "./define_experiment";

export default function ConductExperiment({ experiment }: { experiment: Experiment }) {
  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <h3 className="text-2xl font-bold">Conduct Experiment</h3>
      <ModuleSelectAndConfig>
        <div>test</div>
      </ModuleSelectAndConfig>
    </div>
  )
}