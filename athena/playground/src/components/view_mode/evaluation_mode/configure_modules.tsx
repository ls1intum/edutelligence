import { Experiment } from "./define_experiment";

export default function ConfigureModules({
  experiment,
}: {
  experiment: Experiment;
}) {
  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <div className="flex flex-row justify-between items-center">
        <h3 className="text-2xl font-bold">Configure Modules</h3>
      </div>
    </div>
  );
}
