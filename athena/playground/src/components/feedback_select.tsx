import useSWR from "swr";
import Feedback from "@/model/feedback";
import fetcher from "@/helpers/fetcher";
import baseUrl from "@/helpers/base_url";

export default function FeedbackSelect(
    {exercise_id, submission_id, feedback, onChange}: { exercise_id?: number, submission_id?: number, feedback: Feedback | null, onChange: (feedback: Feedback) => void}
) {
    const {data, error, isLoading} = useSWR(`${baseUrl}/api/feedbacks`, fetcher);
    if (error) return <div>failed to load</div>;
    if (isLoading) return <div>loading...</div>;

    let filteredFeedbacks = data;
    if (exercise_id) {
        filteredFeedbacks = filteredFeedbacks.filter((fb: Feedback) => fb.exercise_id === exercise_id);
    }
    if (submission_id) {
        filteredFeedbacks = filteredFeedbacks.filter((fb: Feedback) => fb.submission_id === submission_id);
    }

    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Feedback</span>
            <select className="border border-gray-300 rounded-md p-2" value={feedback?.id || ""} onChange={e => onChange(filteredFeedbacks.find((fb: Feedback) => fb.id === parseInt(e.target.value)))}>
                <option value={""} disabled>Select a feedback</option>
                {filteredFeedbacks.map((fb: Feedback) => <option key={fb.id} value={fb.id}>{fb.id} {fb.text}</option>)}
            </select>
        </label>
    );
}
