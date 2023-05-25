import {useState} from "react";
import { Submission } from "@/model/submission";
import { Exercise } from "@/model/exercise";
import ExerciseSelect from "@/components/exercise_select";
import ModuleResponse from "@/model/module_response";
import ModuleResponseView from "@/components/module_response_view";
import {ModuleMeta} from "@/model/health_response";

async function sendSubmissions(athenaUrl: string, athenaSecret: string, module: ModuleMeta, exercise: Exercise | null): Promise<ModuleResponse | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    const submissionsResponse = await fetch(`/api/submissions?${ new URLSearchParams({exercise_id: exercise.id.toString()}) }`);
    const submissions: Submission[] = await submissionsResponse.json();
    let response;
    try {
        const athenaSubmissionsUrl = `${athenaUrl}/modules/${module.type}/${module.name}/submissions`;
        response = await fetch(`/api/athena_request?${ new URLSearchParams({url: athenaSubmissionsUrl}) }`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Secret': athenaSecret
            },
            body: JSON.stringify({exercise, submissions})
        });
    } catch (e) {
        console.error(e);
        alert("Failed to send submissions to Athena: Failed to fetch. Is the URL correct?");
        return;
    }
    if (!response.ok) {
        console.error(response);
        alert(`Athena responded with status code ${response.status}`);
        return {
            module_name: "Unknown",
            status: response.status,
            data: await response.text()
        };
    }
    alert(`${submissions.length} submissions sent successfully!`);
    return {
        ...await response.json(),
        status: response.status
    };
}

export default function SendSubmissions(
    { athenaUrl, athenaSecret, module }: { athenaUrl: string, athenaSecret: string, module: ModuleMeta }
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
            <ExerciseSelect exerciseType={module.type} exercise={exercise} onChange={setExercise} />
            <ModuleResponseView response={response} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    sendSubmissions(athenaUrl, athenaSecret, module, exercise)
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