import {useState} from "react";
import Submission from "@/pages/model/submission";
import Exercise from "@/pages/model/exercise";
import ExerciseSelect from "@/pages/components/exercise_select";

async function sendSubmissions(athenaUrl: string, exercise: Exercise | null) {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    const submissionsResponse = await fetch(`/api/submissions?${ new URLSearchParams({exercise_id: exercise.id.toString()}) }`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            exercise_id: exercise.id
        })
    });
    const submissions: Submission[] = await submissionsResponse.json();
    let athenaResponse;
    try {
        const athenaSubmissionsUrl = `${athenaUrl}/submissions`;
        athenaResponse = await fetch(`/api/athena_request?${ new URLSearchParams({url: athenaSubmissionsUrl}) }`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({submissions})
        });
    } catch (e) {
        console.error(e);
        alert("Failed to send submissions to Athena: Failed to fetch. Is the URL correct?");
        return;
    }
    if (athenaResponse.status !== 200) {
        console.error(athenaResponse);
        alert(`Athena responded with status code ${athenaResponse.status}`);
        return;
    }
    alert(`${submissions.length} submissions sent successfully!`);
}

export default function SendSubmissions(
    { athenaUrl }: { athenaUrl: string }
) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [loading, setLoading] = useState<boolean>(false);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Send Submissions</h1>
            <p className="text-gray-500 mb-4">Send submissions to Athena for grading.</p>
            <ExerciseSelect exercise={exercise} onChange={setExercise} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    sendSubmissions(athenaUrl, exercise).finally(() => setLoading(false));
                } }
                disabled={loading}
            >
                {loading ? "Loading..." : "Send Submissions"}
            </button>
        </div>
    );
}