import GetConfigSchema from "@/components/view_mode/module_requests/get_config_schema";
import SendSubmissions from "@/components/view_mode/module_requests/send_submissions";
import SendFeedback from "@/components/view_mode/module_requests/send_feedback";
import RequestFeedbackSuggestions from "@/components/view_mode/module_requests/request_feedback_suggestions";
import SelectSubmission from "@/components/view_mode/module_requests/request_submission_selection";
import ModuleSelectAndConfig from "./module_select_and_config";

export default function ModuleRequests() {
  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Module Requests</h2>
      <ModuleSelectAndConfig className="bg-white rounded-md p-4 mb-8">
        <GetConfigSchema />
        <SendSubmissions />
        <SelectSubmission />
        <SendFeedback />
        <RequestFeedbackSuggestions />
      </ModuleSelectAndConfig>
    </>
  );
}
