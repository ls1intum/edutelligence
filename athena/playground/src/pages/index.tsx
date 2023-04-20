import {Inter} from 'next/font/google';
import {useState} from "react";
import AthenaUrlInput from "@/pages/components/athena_url_input";
import SendSubmissions from "@/pages/components/send_submissions";
import SendFeedback from "@/pages/components/send_feedback";

const inter = Inter({subsets: ['latin']});

export default function Home() {
    const [athenaUrl, setAthenaUrl] = useState<string>("http://127.0.0.1:5000");

    return (
        <main className="flex min-h-screen flex-col p-24">
            <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
            <AthenaUrlInput value={athenaUrl} onChange={setAthenaUrl} />
            <SendSubmissions athenaUrl={athenaUrl} />
            <SendFeedback athenaUrl={athenaUrl} />
        </main>
    );
}
