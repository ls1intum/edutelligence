import useSWR from "swr";
import { Exercise } from "@/model/exercise";
import fetcher from "@/helpers/fetcher";
import baseUrl from "@/helpers/base_url";

export default function ExerciseSelect(
    {exercise, exerciseType, onChange}: { exercise: Exercise | null, exerciseType: string, onChange: (exercise: Exercise) => void}
) {
    const {data, error, isLoading} = useSWR(`${baseUrl}/api/exercises`, fetcher);
    if (error) return <div>failed to load</div>;
    if (isLoading) return <div>loading...</div>;
    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Exercise</span>
            <select className="border border-gray-300 rounded-md p-2" value={exercise?.id ?? ""} onChange={e => onChange(data.find((ex: Exercise) => ex.id === parseInt(e.target.value)))}>
                <option value={""} disabled>Select an exercise</option>
                {
                    data
                        .map((ex: Exercise) => {
                            return <option key={ex.id} value={ex.id} disabled={ex.type !== exerciseType}>
                                {ex.id} {ex.type}: {ex.title}
                            </option>;
                        })
                }
            </select>
        </label>
    );
}
