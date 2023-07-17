import React, { useState } from "react";
import BaseInfoHeader from "@/components/base_info_header";
import ModuleRequests from "@/components/module_requests";
import { ModuleMeta } from "@/model/health_response";
import { Mode } from "@/model/mode";

export default function Home() {
  const [athenaUrl, setAthenaUrl] = useState<string>(() => {
    // Default value if location is not defined (for server-side rendering)
    let defaultUrl = "http://127.0.0.1:5000";
    if (
      typeof window !== "undefined" &&
      window.location.hostname !== "localhost"
    ) {
      // default url for non-local development is the origin of the current page
      defaultUrl = window.location.origin;
    }
    return defaultUrl;
  });
  const [athenaSecret, setAthenaSecret] = useState<string>("");
  const [module, setModule] = useState<ModuleMeta | undefined>(undefined);
  const [moduleConfig, setModuleConfig] = useState<any>(undefined);
  const [mode, setMode] = useState<Mode>("example");

  return (
    <main className="flex min-h-screen flex-col p-24">
      <h1 className="text-6xl font-bold text-white mb-8">Playground</h1>
      <BaseInfoHeader
        athenaUrl={athenaUrl}
        onChangeAthenaUrl={setAthenaUrl}
        athenaSecret={athenaSecret}
        onChangeAthenaSecret={setAthenaSecret}
        module={module}
        onChangeModule={setModule}
        moduleConfig={moduleConfig}
        onChangeModuleConfig={setModuleConfig}
        mode={mode}
        onChangeMode={setMode}
      />
      {module && (
        <ModuleRequests
          mode={mode}
          athenaUrl={athenaUrl}
          athenaSecret={athenaSecret}
          module={module}
          moduleConfig={moduleConfig}
        />
      )}
    </main>
  );
}
