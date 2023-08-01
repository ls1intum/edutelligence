import type { HealthResponse } from "@/model/health_response";
import useHealth from "@/hooks/health";

export default function ExerciseTypeSelect({
  exerciseType,
  onChangeExerciseType,
}: {
  exerciseType: string | undefined;
  onChangeExerciseType: (type: string) => void;
}) {
  const { data, error } = useHealth();
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (!data) return <div className="text-gray-500 text-sm">Loading...</div>;

  const getModuleTypes = (healthResponse: HealthResponse): { healthy: boolean; type: string; }[] => {
    const types = new Set<string>();
    Object.values(healthResponse.modules).forEach((module) => {
      types.add(module.type);
    });

    return Array.from(types).map((type) => {
      return {
        type,
        healthy: Object.values(healthResponse.modules).filter((module) => module.type === type).some((module) => module.healthy),
      }
    });
  }

  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Exercise Type</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={exerciseType ?? ""}
        onChange={(e) => onChangeExerciseType(e.target.value)}
      >
        <option value={""} disabled>
          Select an exercise type
        </option>
        {getModuleTypes(data).map(({ type, healthy }) => {
          return (
            <option key={type} value={type} disabled={!healthy}>
              {type}
              {healthy ? "" : " (none healthy!)"}
            </option>
          );
        })}
      </select>
    </label>
  );
}
