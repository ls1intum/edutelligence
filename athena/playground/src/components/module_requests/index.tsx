import type { ModuleMeta } from "@/model/health_response";
import type { Mode } from "@/model/mode";

import GetConfigSchema from "@/components/module_requests/get_config_schema";
import SendSubmissions from "@/components/module_requests/send_submissions";
import SendFeedback from "@/components/module_requests/send_feedback";
import RequestFeedbackSuggestions from "@/components/module_requests/request_feedback_suggestions";
import SelectSubmission from "@/components/module_requests/request_submission_selection";
import FeedbackEditorTest from "./feedback_editor_test";

export type ModuleRequestProps = {
  mode: Mode;
  athenaUrl: string;
  athenaSecret: string;
  module: ModuleMeta;
  moduleConfig: any;
};

export default function ModuleRequests(props: ModuleRequestProps) {
  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Module Requests</h2>
      <FeedbackEditorTest {...props} />
      <GetConfigSchema {...props} />
      <SendSubmissions {...props} />
      <SelectSubmission {...props} />
      <SendFeedback {...props} />
      <RequestFeedbackSuggestions {...props} />
    </>
  );
}
