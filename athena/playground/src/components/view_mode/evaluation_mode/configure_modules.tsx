import type { ModuleMeta } from "@/model/health_response";
import type { Experiment } from "./define_experiment";

import { useState } from "react";

import ModuleAndConfigSelect from "@/components/selectors/module_and_config_select";

export default function ConfigureModules({
  experiment,
}: {
  experiment: Experiment;
}) {
  const [moduleAndConfig, setModuleAndConfig] = useState<{ module: ModuleMeta; moduleConfig: any } | undefined>(undefined);

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <div className="flex flex-row justify-between items-center">
        <h3 className="text-2xl font-bold">Configure Modules</h3>
      </div>
      <div className="sticky top-0 bg-white p-2 border-b border-gray-300">
        <input type="text" placeholder="Configuration name" className="w-full rounded-md p-2 border border-gray-300" />
      </div>
      <ModuleAndConfigSelect exerciseType={experiment.exerciseType} moduleAndConfig={moduleAndConfig} onChangeModuleAndConfig={setModuleAndConfig} />
    </div>
  );
}
