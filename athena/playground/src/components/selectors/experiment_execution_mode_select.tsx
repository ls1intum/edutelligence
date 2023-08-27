export type ExecutionMode = "incremental" | "batch";

type ExperimentExecutionModeSelectProps = {
  disabled?: boolean;
  executionMode?: ExecutionMode;
  onChangeExecutionMode: (executionMode: ExecutionMode) => void;
};

export default function ExperimentExecutionModeSelect({
  disabled,
  executionMode,
  onChangeExecutionMode: onChangeExperimentMode,
}: ExperimentExecutionModeSelectProps) {
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Execution Mode</span>
      <select
        disabled={disabled}
        className="border border-gray-300 rounded-md p-2 disabled:opacity-50"
        value={executionMode ?? ""}
        onChange={(e) =>
          onChangeExperimentMode(e.target.value as ExecutionMode)
        }
      >
        <option value={""} disabled>
          Select an execution mode
        </option>
        {/* TODO: Add back in incremental learning mode
        <option value={"incremental"}>
          Incremental learning mode (one submission at a time)
        </option> */}
        <option value={"batch"}>Batch mode (all submissions at once)</option>
      </select>
    </label>
  );
}
