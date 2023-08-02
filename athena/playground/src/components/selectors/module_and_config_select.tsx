import type { ModuleMeta } from "@/model/health_response";

import { ModuleProvider } from "@/hooks/module_context";
import useConfigSchema from "@/hooks/athena/config_schema";

import Disclosure from "@/components/disclosure";
import ModuleSelect from "@/components/selectors/module_select";
import ModuleConfigSelect from "@/components/selectors/module_config_select";

type ModuleConfigProps = {
  module: ModuleMeta;
  moduleConfig: any;
  onChangeConfig: (newConfig: any) => void;
  showOverrideCheckbox?: boolean;
  collapsibleConfig?: boolean;
};

function ModuleConfig({
  module,
  moduleConfig,
  onChangeConfig,
  showOverrideCheckbox,
  collapsibleConfig,
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
          {showOverrideCheckbox && (
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
            </>
          )}
          {(moduleConfig !== undefined || !showOverrideCheckbox) &&
            (collapsibleConfig ? (
              <Disclosure title="Configuration" openedInitially>
                <ModuleConfigSelect
                  module={module}
                  moduleConfig={moduleConfig}
                  onChangeConfig={onChangeConfig}
                />
              </Disclosure>
            ) : (
              <ModuleConfigSelect
                module={module}
                moduleConfig={moduleConfig}
                onChangeConfig={onChangeConfig}
              />
            ))}
        </>
      )}
    </div>
  );
}

type ModuleAndConfig = {
  module: ModuleMeta;
  moduleConfig: any;
};

type ModuleAndConfigSelectProps = {
  exerciseType?: string;
  showOverrideCheckbox?: boolean;
  collapsibleConfig?: boolean;
  moduleAndConfig: ModuleAndConfig | undefined;
  onChangeModuleAndConfig: (newModuleAndConfig: ModuleAndConfig) => void;
};

export default function ModuleAndConfigSelect({
  exerciseType,
  showOverrideCheckbox,
  collapsibleConfig,
  moduleAndConfig,
  onChangeModuleAndConfig,
}: ModuleAndConfigSelectProps) {
  return (
    <div>
      <ModuleSelect
        exerciseType={exerciseType}
        module={moduleAndConfig?.module}
        onChange={(newModule) => {
          onChangeModuleAndConfig({
            module: newModule,
            moduleConfig: undefined,
          });
        }}
      />
      {moduleAndConfig?.module && (
        <ModuleProvider
          module={moduleAndConfig.module}
          moduleConfig={moduleAndConfig.moduleConfig}
        >
          <ModuleConfig
            showOverrideCheckbox={showOverrideCheckbox}
            collapsibleConfig={collapsibleConfig}
            module={moduleAndConfig.module}
            moduleConfig={moduleAndConfig.moduleConfig}
            onChangeConfig={(newConfig) => {
              onChangeModuleAndConfig({
                module: moduleAndConfig.module,
                moduleConfig: newConfig,
              });
            }}
          />
        </ModuleProvider>
      )}
    </div>
  );
}
