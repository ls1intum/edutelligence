import {Inter} from 'next/font/google';
import Exercise from "@/pages/model/exercise";
import Submission from "@/pages/model/submission";
import Feedback from "@/pages/model/feedback";
import {useState} from "react";
import AthenaUrlInput from "@/pages/components/athena_url_input";
import SendSubmissions from "@/pages/components/send_submissions";

const inter = Inter({subsets: ['latin']});

export default function Home() {
    const [athenaUrl, setAthenaUrl] = useState<string>("http://127.0.0.1:5000");
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [submission, setSubmission] = useState<Submission | null>(null);
    const [feedback, setFeedback] = useState<Feedback | null>(null);

    return (
        <main className="flex min-h-screen flex-col p-24">
            <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
            <AthenaUrlInput value={athenaUrl} onChange={setAthenaUrl} />
            <SendSubmissions athenaUrl={athenaUrl} />
        </main>
    );
}
