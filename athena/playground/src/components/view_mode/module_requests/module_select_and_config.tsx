import type { ModuleMeta } from "@/model/health_response";

import { ReactNode, useState } from "react";

import { ModuleProvider } from "@/hooks/module_context";
import useConfigSchema from "@/hooks/athena/config_schema";

import Disclosure from "@/components/disclosure";
import ModuleSelect from "@/components/selectors/module_select";
import ModuleConfigSelect from "@/components/selectors/module_config_select";

type ModuleConfigProps = {
  module: ModuleMeta;
  moduleConfig: any;
  onChangeConfig: (newConfig: any) => void;
};

function ModuleConfig({
  module,
  moduleConfig,
  onChangeConfig,
}: ModuleConfigProps) {
  const { data, error, isLoading } = useConfigSchema();

  return (
    <div className="mt-2 space-y-1">
      {isLoading && <p className="text-gray-500">Loading...</p>}
      {error &&
        (error.status === 404 ? (
          <p className="text-gray-500">
            Config options not available, not implemented in the module
          </p>
        ) : (
          <p className="text-red-500">
            Failed to get config options from Athena
          </p>
        ))}
      {data && (
        <>
          <p className="text-gray-500">
            This module has a custom configuration. You can use the default
            configuration or provide your own.
          </p>
          <label className="flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={moduleConfig !== undefined}
              onChange={(e) => {
                if (e.target.checked) {
                  onChangeConfig({});
                } else {
                  onChangeConfig(undefined);
                }
              }}
            />
            <div className="ml-2 text-gray-700 font-normal">
              Use custom module config
            </div>
          </label>
          {moduleConfig !== undefined && (
            <Disclosure title="Configuration" openedInitially>
              <ModuleConfigSelect
                module={module}
                moduleConfig={moduleConfig}
                onChangeConfig={onChangeConfig}
              />
            </Disclosure>
          )}
        </>
      )}
    </div>
  );
}

export default function ModuleSelectAndConfig({ children, className }: { children: ReactNode; className?: string }) {
  const [module, setModule] = useState<ModuleMeta | undefined>(undefined);
  const [moduleConfig, setModuleConfig] = useState<any>(undefined);

  return (
    <>
      <div className={className}>
        <ModuleSelect module={module} onChange={setModule} />
        {module && (
          <ModuleProvider module={module} moduleConfig={moduleConfig}>
            <ModuleConfig
              module={module}
              moduleConfig={moduleConfig}
              onChangeConfig={setModuleConfig}
            />
          </ModuleProvider>
        )}
      </div>
      {module && (
        <ModuleProvider module={module} moduleConfig={moduleConfig}>
          {children}
        </ModuleProvider>
      )}
    </>
  );
}
