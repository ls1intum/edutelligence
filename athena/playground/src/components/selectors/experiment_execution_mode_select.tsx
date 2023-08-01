export type ExecutionMode = "incremental" | "batch";

export default function ExperimentExecutionModeSelect({
  executionMode,
  onChangeExecutionMode: onChangeExperimentMode,
}: {
  executionMode: ExecutionMode | undefined;
  onChangeExecutionMode: (executionMode: ExecutionMode) => void;
}) {
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Execution Mode</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={executionMode ?? ""}
        onChange={(e) =>
          onChangeExperimentMode(e.target.value as ExecutionMode)
        }
      >
        <option value={""} disabled>
          Select an execution mode
        </option>
        <option value={"incremental"}>
          Incremental learning mode (one submission at a time)
        </option>
        <option value={"batch"}>Batch mode (all submissions at once)</option>
      </select>
  </label>
  );
}
