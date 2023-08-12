import type { ModuleMeta } from "@/model/health_response";

import GetConfigSchema from "@/components/module_requests/get_config_schema";
import SendSubmissions from "@/components/module_requests/send_submissions";
import SendFeedback from "@/components/module_requests/send_feedback";
import RequestFeedbackSuggestions from "@/components/module_requests/request_feedback_suggestions";
import SelectSubmission from "@/components/module_requests/request_submission_selection";

// TODO: REMOVE THIS BEFORE MERGING TO MAIN
import FeedbackEditorTest from "./feedback_editor_test";

export default function ModuleRequests({ module }: { module: ModuleMeta }) {
  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Module Requests</h2>
      <FeedbackEditorTest module={module} /> {/* TODO: REMOVE THIS BEFORE MERGING TO MAIN */}
      <GetConfigSchema module={module} />
      <SendSubmissions module={module} />
      <SelectSubmission module={module} />
      <SendFeedback module={module} />
      <RequestFeedbackSuggestions module={module} />
    </>
  );
}
