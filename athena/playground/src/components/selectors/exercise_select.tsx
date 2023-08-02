import type { Exercise } from "@/model/exercise";
import useExercises from "@/hooks/playground/exercises";

type ExerciseSelectProps = {
  exercise?: Exercise;
  exerciseType: string;
  onChange: (exercise: Exercise) => void;
  disabled?: boolean;
};

export default function ExerciseSelect({
  exercise,
  exerciseType,
  onChange,
  disabled,
}: ExerciseSelectProps) {
  const { data, error, isLoading } = useExercises()
  if (error) return <div className="text-red-500 text-sm">Failed to load</div>;
  if (isLoading) return <div className="text-gray-500 text-sm">Loading...</div>;
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Exercise</span>
      <select
        className="border border-gray-300 rounded-md p-2 disabled:opacity-50"
        value={exercise?.id ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(data!.find((ex: Exercise) => ex.id === parseInt(e.target.value))!)}
      >
        <option value={""} disabled>
          Select an exercise
        </option>
        {data && data
          .sort((a: Exercise, b: Exercise) => a.id - b.id)
          .map((ex: Exercise) => {
            return ex.type === exerciseType ? (
              <option key={ex.id} value={ex.id}>
                {ex.id} {ex.type}: {ex.title}
              </option>
            ) : null;
          })}
      </select>
    </label>
  );
}
