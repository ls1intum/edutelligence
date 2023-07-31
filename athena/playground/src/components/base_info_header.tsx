import { useBaseInfo, useBaseInfoDispatch } from "@/hooks/base_info_context";
import useConfigSchema from "@/hooks/athena/config_schema";

import Health from "@/components/health";
import ModuleSelect from "@/components/selectors/module_select";
import DataSelect from "@/components/selectors/data_select";
import ModuleConfigSelect from "@/components/selectors/module_config_select";
import Disclosure from "@/components/disclosure";

export default function BaseInfoHeader() {
  const {
    mode,
    athenaUrl,
    athenaSecret,
    module,
    moduleConfig,
  } = useBaseInfo();
  const dispatch = useBaseInfoDispatch();
  const { data, error, isLoading } = useConfigSchema();

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <label className="flex flex-col">
        <span className="text-lg font-bold">Athena URL</span>
        <input
          className="border border-gray-300 rounded-md p-2"
          value={athenaUrl}
          onChange={(e) => dispatch({ type: "SET_ATHENA_URL", payload: e.target.value })}
        />
      </label>
      <Health />
      <label className="flex flex-col mt-4">
        <span className="text-lg font-bold">Secret</span>
        <p className="text-gray-500 mb-2">
          This is the secret that you configured in Athena. It&apos;s optional
          for local development, but required for production setups.
        </p>
        <input
          className="border border-gray-300 rounded-md p-2"
          value={athenaSecret}
          placeholder="Optional, only required for production setups"
          onChange={(e) => dispatch({ type: "SET_ATHENA_SECRET", payload: e.target.value })}
        />
      </label>
      <br />
      <ModuleSelect
        module={module}
        onChange={(value) => dispatch({ type: "SET_MODULE", payload: value })}
      />
      {module && (
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
                      dispatch({ type: "SET_MODULE_CONFIG", payload: {}});
                    } else {
                      dispatch({ type: "SET_MODULE_CONFIG", payload: undefined});
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
                    onChangeConfig={(config) =>
                      dispatch({ type: "SET_MODULE_CONFIG", payload: config })
                    }
                  />
                </Disclosure>
              )}
            </>
          )}
        </div>
      )}
      <br />
      <DataSelect 
        mode={mode} 
        onChangeMode={(mode) => dispatch({ type: "SET_MODE", payload: mode })} 
      />
    </div>
  );
}
