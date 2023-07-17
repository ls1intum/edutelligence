/* Modified version of:
 * https://github.com/rjsf-team/react-jsonschema-form/blob/main/packages/core/src/components/templates/DescriptionField.tsx
 * 
 * To enable markdown rendering for all description fields by default
 * Also needed to enable markdown rendering for the description of the object and not just the description of the fields
 */
import { DescriptionFieldProps, FormContextType, RJSFSchema, StrictRJSFSchema } from '@rjsf/utils';
import ReactMarkdown from "react-markdown";

/** The `DescriptionField` is the template to use to render the description of a field
 *
 * @param props - The `DescriptionFieldProps` for this component
 */
export default function DescriptionField<
  T = any,
  S extends StrictRJSFSchema = RJSFSchema,
  F extends FormContextType = any
>(props: DescriptionFieldProps<T, S, F>) {
  const { id, description } = props;
  if (!description) {
    return null;
  }
  if (typeof description === 'string') {
    return (
      <p id={id} className='field-description'>
        <ReactMarkdown>{description}</ReactMarkdown>
      </p>
    );
  } else {
    return (
      <div id={id} className='field-description'>
        {description}
      </div>
    );
  }
}
