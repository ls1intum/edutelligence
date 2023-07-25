import React from "react";
import BaseInfoHeader from "@/components/base_info_header";
import ModuleRequests from "@/components/module_requests";
import { useBaseInfo } from "@/hooks/base_info_context";

export default function Playground() {
  const { module } = useBaseInfo();

  return (
    <main className="flex min-h-screen flex-col p-24">
      <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
      <BaseInfoHeader />
      {module && (<ModuleRequests module={module} />)}
    </main>
  );
}
