import {useState} from "react";
import Submission from "@/pages/model/submission";
import Exercise from "@/pages/model/exercise";
import ExerciseSelect from "@/pages/components/exercise_select";
import ModuleResponse from "@/pages/model/module_response";
import ModuleResponseView from "@/pages/components/module_response_view";

async function sendSubmissions(athenaUrl: string, exercise: Exercise | null): Promise<ModuleResponse | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    const submissionsResponse = await fetch(`/api/submissions?${ new URLSearchParams({exercise_id: exercise.id.toString()}) }`);
    const submissions: Submission[] = await submissionsResponse.json();
    let athenaResponse;
    try {
        const athenaSubmissionsUrl = `${athenaUrl}/submissions`;
        athenaResponse = await fetch(`/api/athena_request?${ new URLSearchParams({url: athenaSubmissionsUrl}) }`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({exercise, submissions})
        });
    } catch (e) {
        console.error(e);
        alert("Failed to send submissions to Athena: Failed to fetch. Is the URL correct?");
        return;
    }
    if (!athenaResponse.ok) {
        console.error(athenaResponse);
        alert(`Athena responded with status code ${athenaResponse.status}`);
        return {
            module_name: "Unknown",
            status: athenaResponse.status,
            data: await athenaResponse.text()
        };
    }
    alert(`${submissions.length} submissions sent successfully!`);
    return {
        ...await athenaResponse.json(),
        status: athenaResponse.status
    };
}

export default function SendSubmissions(
    { athenaUrl }: { athenaUrl: string }
) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [response, setResponse] = useState<ModuleResponse | undefined>(undefined);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Send Submissions</h1>
            <p className="text-gray-500 mb-4">
                Send all submissions for an exercise to Athena.
                This usually happens when the exercise deadline is reached in the LMS.
                The matching module for the exercise will receive the submissions at the function annotated with <code>@submission_consumer</code>.
            </p>
            <ExerciseSelect exercise={exercise} onChange={setExercise} />
            <ModuleResponseView response={response} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    sendSubmissions(athenaUrl, exercise)
                        .then(setResponse)
                        .finally(() => setLoading(false));
                } }
                disabled={loading}
            >
                {loading ? "Loading..." : "Send Submissions"}
            </button>
        </div>
    );
}