import type { ModuleMeta } from "@/model/health_response";
import useHealth from "@/hooks/health";

type ModuleSelectProps = {
  disabled?: boolean;
  exerciseType?: string;
  module: ModuleMeta | undefined;
  onChange: (module: ModuleMeta) => void;
}

export default function ModuleSelect({
  disabled,
  exerciseType,
  module,
  onChange,
}: ModuleSelectProps) {
  const { data, error } = useHealth();
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (!data) return <div className="text-gray-500 text-sm">Loading...</div>;
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Module</span>
      <select
        disabled={disabled}
        className="border border-gray-300 rounded-md p-2 disabled:opacity-50"
        value={module?.name ?? ""}
        onChange={(e) => onChange(data.modules[e.target.value])}
      >
        <option value={""} disabled>
          Select a module
        </option>
        {Object.entries(data.modules).map(([moduleName, { healthy, type }]) => {
          if (exerciseType && type !== exerciseType) return null;
          return (
            <option key={moduleName} value={moduleName}>
              {moduleName}
              {healthy ? "" : " (not healthy!)"}
            </option>
          );
        })}
      </select>
    </label>
  );
}
