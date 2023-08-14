import type { ModuleMeta } from "@/model/health_response";

import GetConfigSchema from "@/components/module_requests/get_config_schema";
import SendSubmissions from "@/components/module_requests/send_submissions";
import SendFeedbacks from "@/components/module_requests/send_feedbacks";
import RequestFeedbackSuggestions from "@/components/module_requests/request_feedback_suggestions";
import SelectSubmission from "@/components/module_requests/request_submission_selection";

export default function ModuleRequests({ module }: { module: ModuleMeta }) {
  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Module Requests</h2>
      <GetConfigSchema module={module} />
      <SendSubmissions module={module} />
      <SelectSubmission module={module} />
      <SendFeedbacks module={module} />
      <RequestFeedbackSuggestions module={module} />
    </>
  );
}
