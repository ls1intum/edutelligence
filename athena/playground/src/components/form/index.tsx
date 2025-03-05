import { ThemeProps, withTheme } from "@rjsf/core";
import TextAreaWidget from "./textarea_widget";
import DescriptionField from "./description_field";

const theme: ThemeProps = {
  widgets: { textarea: TextAreaWidget },
  templates: {
    DescriptionFieldTemplate: DescriptionField,
  }
};

const ThemedForm = withTheme(theme);
export default ThemedForm;
