import type { ModuleMeta } from "@/model/health_response";

import { useState } from "react";

import GetConfigSchema from "@/components/view_mode/module_requests/get_config_schema";
import SendSubmissions from "@/components/view_mode/module_requests/send_submissions";
import SendFeedback from "@/components/view_mode/module_requests/send_feedback";
import RequestFeedbackSuggestions from "@/components/view_mode/module_requests/request_feedback_suggestions";
import SelectSubmission from "@/components/view_mode/module_requests/request_submission_selection";
import ModuleAndConfigSelect from "@/components/selectors/module_and_config_select";
import { ModuleProvider } from "@/hooks/module_context";

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
          <SendFeedback />
          <RequestFeedbackSuggestions />
        </ModuleProvider>
      )}
    </>
  );
}
