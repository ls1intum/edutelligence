import {
  RJSFSchema,
  toPathSchema,
  UIOptionsType,
  ValidatorType,
  PathSchema,
} from "@rjsf/utils";


/** Helper to create a UI schema from a JSON schema for react-jsonschema-form
 * 
 * It will recursively go through all the properties of the schema and call the `value` 
 * function with the property name as argument. This allows to set the UI options for
 * each property individually, making it easy to customize the form.
 * 
 * More info on react-jsonschema-form UI schema:
 * https://rjsf-team.github.io/react-jsonschema-form/docs/api-reference/uiSchema
 * 
 * @param validator - The validator to use
 * @param schema - The JSON schema
 * @param value - A function that will be called with the property name as argument
 * @returns The UI schema
 */
export function getUISchema(
  validator: ValidatorType,
  schema: RJSFSchema,
  value: (property: string) => UIOptionsType
) {
  const paths = toPathSchema(validator, schema, undefined, schema);
  function recursiveSetValueForPaths(property: string, paths: PathSchema) {
    const properties = Object.keys(paths).filter((path) => path !== "$name");
    if (properties.length === 0) {
      return value(property);
    }
    return {
      ...properties.reduce((acc, property) => {
        acc[property] = recursiveSetValueForPaths(property, paths[property]!);
        return acc;
      }, {} as UIOptionsType),
    };
  }
  return recursiveSetValueForPaths("__root__", paths);
}
