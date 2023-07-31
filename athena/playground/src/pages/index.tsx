import React from "react";
import BaseInfoHeader from "@/components/base_info_header";
import ModuleRequests from "@/components/view_mode/module_requests";

export default function Playground() {
  return (
    <main className="flex min-h-screen flex-col p-24">
      <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
      <BaseInfoHeader />
      <ModuleRequests />
    </main>
  );
}
