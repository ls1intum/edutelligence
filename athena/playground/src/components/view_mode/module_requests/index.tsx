import type { ModuleMeta } from "@/model/health_response";

import { useState } from "react";

import { ModuleProvider } from "@/hooks/module_context";
import ModuleAndConfigSelect from "@/components/selectors/module_and_config_select";
import GetConfigSchema from "@/components/view_mode/module_requests/get_config_schema";
import SendSubmissions from "@/components/view_mode/module_requests/send_submissions";
import SelectSubmission from "@/components/view_mode/module_requests/request_submission_selection";
import SendFeedbacks from "@/components/view_mode/module_requests/send_feedbacks";
import RequestGradedFeedbackSuggestions from "@/components/view_mode/module_requests/request_graded_feedback_suggestions";
import RequestNonGradedFeedbackSuggestions from "@/components/view_mode/module_requests/request_non_graded_feedback_suggestions";
import RequestEvaluation from "@/components/view_mode/module_requests/request_evaluation";


export default function ModuleRequests() {
  const [moduleAndConfig, setModuleAndConfig] = useState<{ module: ModuleMeta; moduleConfig: any } | undefined>(undefined);

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Module Requests</h2>
      <div className="bg-white rounded-md p-4 mb-8">
        <ModuleAndConfigSelect
          showOverrideCheckbox
          collapsibleConfig
          moduleAndConfig={moduleAndConfig}
          onChangeModuleAndConfig={setModuleAndConfig}
        />
      </div>
      {moduleAndConfig && (
        <ModuleProvider
          module={moduleAndConfig.module}
          moduleConfig={moduleAndConfig.moduleConfig}
        >
          <GetConfigSchema />
          <SendSubmissions />
          <SelectSubmission />
          <SendFeedbacks />
          <RequestGradedFeedbackSuggestions />
          <RequestNonGradedFeedbackSuggestions />
          <RequestEvaluation />
        </ModuleProvider>
      )}
    </>
  );
}
