import type { ModuleMeta } from "@/model/health_response";

import { Dispatch, SetStateAction, useEffect, useState } from "react";
import validator from "@rjsf/validator-ajv8";
import { getDefaultFormState } from "@rjsf/utils";

import useConfigSchema from "@/hooks/athena/config_schema";
import DefaultSchemaFormModuleConfig from "./default_schema_form";
import ModuleLLMConfig from "./module_llm";

// Need to customize the form for some modules?
// You can do that here.
//
// Add custom module config components in case you 
// need to really customize the default schema form 
// (DefaultSchemaFormModuleConfig).
//
// 1. Add your module name to the CustomModuleConfig type i.e.:
//    type CustomModuleConfig = "module_text_llm" | "my_new_module"
// 2. Add your module name to the customModuleConfigComponents object
// 3. Create your component in the same folder as this file
// 4. Add your component to the customModuleConfigComponents object
//
// Use ModuleLLMConfig as example.
type CustomModuleConfig = "module_text_llm";
const customModuleConfigComponents: {
  [key in CustomModuleConfig]: React.FC<ModuleConfigSelectProps>;
} = {
  module_text_llm: ModuleLLMConfig,
};

type SetConfig = Dispatch<SetStateAction<any>>;

export type ModuleConfigSelectProps = {
  configOptions?: any;
  moduleConfig: any;
  onChangeConfig: SetConfig;
};

type ModuleConfigSelectWrapperProps = ModuleConfigSelectProps & {
  module: ModuleMeta;
};

export default function ModuleConfigSelect({
  module,
  moduleConfig,
  onChangeConfig,
}: ModuleConfigSelectWrapperProps) {
  const hasCustomModuleConfigComponent =
    module.name in customModuleConfigComponents;
  const CustomModuleConfigComponent =
    customModuleConfigComponents[module.name as CustomModuleConfig];

  const [formKey, setFormKey] = useState(0);
  const { data, error, isLoading } = useConfigSchema();

  useEffect(() => {
    if (data) {
      const defaultFormData = getDefaultFormState(validator, data, {}, data);
      if (
        Object.keys(moduleConfig).length === 0 &&
        Object.keys(defaultFormData).length !== 0
      ) {
        onChangeConfig(defaultFormData);
        setFormKey(formKey + 1);
      }
    }
  }, [data, formKey, moduleConfig, onChangeConfig]);

  return (
    <>
      {isLoading && <p>Loading...</p>}
      {error &&
        (error.status !== 404 ? (
          <p className="text-red-500">
            Failed to get config options from Athena
          </p>
        ) : (
          <p className="text-gray-500">
            No config options available, not implemented in the module
          </p>
        ))}
      {data &&
        (hasCustomModuleConfigComponent ? (
          <CustomModuleConfigComponent
            configOptions={data.data}
            moduleConfig={moduleConfig}
            onChangeConfig={onChangeConfig}
          />
        ) : (
          <DefaultSchemaFormModuleConfig
            configOptions={data.data}
            moduleConfig={moduleConfig}
            onChangeConfig={onChangeConfig}
          />
        ))}
    </>
  );
}
