import useSWR from "swr";
import {ProgrammingSubmission, Submission, TextSubmission} from "@/model/submission";
import fetcher from "@/helpers/fetcher";
import baseUrl from "@/helpers/base_url";

export default function SubmissionSelect(
    { exercise_id, submission, onChange, isAllSubmissions, setIsAllSubmissions }: { exercise_id?: number, submission: Submission | null, onChange: (submission: Submission) => void, isAllSubmissions?: boolean, setIsAllSubmissions?: (isAllSubmissions: boolean) => void }
) {
    const {data, error, isLoading} = useSWR(`${baseUrl}/api/submissions`, fetcher);
    if (error) return <div>failed to load</div>;
    if (isLoading) return <div>loading...</div>;

    const filteredSubmissions = exercise_id ? data.filter((sub: Submission) => sub.exercise_id === exercise_id) : data;

    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Submission</span>
            <select className="border border-gray-300 rounded-md p-2"
                    value={isAllSubmissions ? "all" : (submission?.id || "")}
                    onChange={e => {
                        const value = e.target.value;
                        if (value === "all") {
                            setIsAllSubmissions!(true);
                        } else {
                            onChange(filteredSubmissions.find((sub: Submission) => sub.id === parseInt(e.target.value)));
                            if (setIsAllSubmissions) setIsAllSubmissions(false);
                        }
                    }}>
                <option value="" disabled>Select a submission</option>
                {
                    isAllSubmissions !== undefined && setIsAllSubmissions !== undefined &&
                    <option key="all" value="all" onClick={() => setIsAllSubmissions(!isAllSubmissions)}>
                        ✨ All submissions
                    </option>
                }
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
