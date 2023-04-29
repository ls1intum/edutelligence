import useSWR from "swr";
import { Exercise } from "@/pages/model/exercise";
import fetcher from "@/pages/fetcher";

export default function ExerciseSelect(
    {exercise, onChange}: { exercise: Exercise | null, onChange: (exercise: Exercise) => void}
) {
    const {data, error, isLoading} = useSWR("/api/exercises", fetcher);
    if (error) return <div>failed to load</div>;
    if (isLoading) return <div>loading...</div>;
    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Exercise</span>
            <select className="border border-gray-300 rounded-md p-2" value={exercise?.id ?? ""} onChange={e => onChange(data.find((ex: Exercise) => ex.id === parseInt(e.target.value)))}>
                <option value={""} disabled>Select an exercise</option>
                {data.map((ex: Exercise) => <option key={ex.id} value={ex.id}>{ex.id} {ex.type}: {ex.title}</option>)}
            </select>
        </label>
    );
}
