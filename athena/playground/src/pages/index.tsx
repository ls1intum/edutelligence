import React from "react";

import { useBaseInfo } from "@/hooks/base_info_context";
import BaseInfoHeader from "@/components/base_info_header";
import ModuleRequests from "@/components/view_mode/module_requests";
import EvaluationMode from "@/components/view_mode/evaluation_mode";
import ComparativeEvaluationStudyManagement from "@/components/view_mode/comparative_evaluation_study";

export default function Playground() {
  const { viewMode } = useBaseInfo();

  return (
    <main className="flex min-h-screen flex-col p-24">
      <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
      <BaseInfoHeader />
      {viewMode === "module_requests" && <ModuleRequests />}
      {viewMode === "evaluation_mode" && <EvaluationMode />}
      {viewMode === "comparative_evaluation_study" && <ComparativeEvaluationStudyManagement />}
    </main>
  );
}
