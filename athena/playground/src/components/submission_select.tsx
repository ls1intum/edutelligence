import useSWR from "swr";
import {ProgrammingSubmission, Submission, TextSubmission} from "@/model/submission";
import fetcher from "@/helpers/fetcher";

export default function SubmissionSelect(
    {exercise_id, submission, onChange}: { exercise_id?: number, submission: Submission | null, onChange: (submission: Submission) => void}
) {
    const {data, error, isLoading} = useSWR("/api/submissions", fetcher);
    if (error) return <div>failed to load</div>;
    if (isLoading) return <div>loading...</div>;

    const filteredSubmissions = exercise_id ? data.filter((sub: Submission) => sub.exercise_id === exercise_id) : data;

    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Submission</span>
            <select className="border border-gray-300 rounded-md p-2" value={submission?.id || ""} onChange={e => onChange(filteredSubmissions.find((sub: Submission) => sub.id === parseInt(e.target.value)))}>
                <option value={""} disabled>Select a submission</option>
                {filteredSubmissions.map((sub: Submission) => {
                    const contentPreview = (sub as TextSubmission)?.content || (sub as ProgrammingSubmission)?.repository_url || "?";
                    return <option
                        key={sub.id}
                        value={sub.id}>
                        {sub.id} {contentPreview.substring(0, 80)}
                    </option>;
                })}
            </select>
        </label>
    );
}
