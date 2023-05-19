import React, {useEffect, useState} from "react";
import BaseInfoHeader from "@/components/base_info_header";
import SendSubmissions from "@/components/send_submissions";
import SendFeedback from "@/components/send_feedback";
import RequestFeedbackSuggestions from "@/components/request_feedback_suggestions";
import SelectSubmission from "@/components/request_submission_selection";
import {ModuleMeta} from "@/model/health_response";

export default function Home() {
    const [athenaUrl, setAthenaUrl] = useState<string>("http://127.0.0.1:5000");
    const [module, setModule] = useState<ModuleMeta | undefined>(undefined);

    return (
        <main className="flex min-h-screen flex-col p-24">
            <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
            <BaseInfoHeader athenaUrl={athenaUrl} onChangeAthenaUrl={setAthenaUrl} module={module} onChangeModule={setModule}/>
            {module && <>
                <SendSubmissions athenaUrl={athenaUrl} module={module}/>
                <SelectSubmission athenaUrl={athenaUrl} module={module}/>
                <SendFeedback athenaUrl={athenaUrl} module={module}/>
                <RequestFeedbackSuggestions athenaUrl={athenaUrl} module={module}/>
            </>}
        </main>
    );
}
