import type ModuleResponse from "@/model/module_response";

import {ReactNode} from "react";
import Disclosure from "@/components/disclosure";

export default function ModuleResponseView({
  response,
  children,
}: {
  response?: ModuleResponse;
  children?: ReactNode | null;
}) {
  if (!response) {
    return null;
  }
  let formattedData = response.data;
  let formattedMeta = response.meta;
  try {
    formattedData = JSON.parse(formattedData);
  } catch (e) {
    // continue to show the non-formatted response string
  }
  try {
    formattedMeta = JSON.parse(formattedMeta);
  } catch (e) {
    // continue to show the non-formatted response string
  }
  if (typeof formattedData === "object") {
    formattedData = JSON.stringify(formattedData, undefined, 2);
  }
  if (typeof formattedMeta === "object") {
    formattedMeta = JSON.stringify(formattedMeta, undefined, 2);
  }
  // show response.module_name and the formattedData
  return (
    <div className="flex flex-col">
      <h2 className="text-2xl font-bold mb-4 mt-2">Response</h2>
      <div className="flex flex-col">
        <span className="font-bold mb-4">Used module:</span>
        <span className="mb-4">{response.module_name}</span>
      </div>
      <div className="flex flex-col">
        <span className="font-bold mb-4">Status code:</span>
        <span className="mb-4">{response.status}</span>
      </div>
      {formattedMeta !== undefined && (
        <Disclosure
          title="Meta:"
          openedInitially
          noContentIndent
          className={{ trigger: "font-bold text-black" }}
        >
          <pre className="mb-4 bg-gray-100 p-4 rounded-md overflow-x-auto whitespace-pre-wrap">
            {formattedMeta}
          </pre>
        </Disclosure>
      )}
      <Disclosure
        title="Data:"
        openedInitially
        noContentIndent
        className={{ trigger: "font-bold text-black" }}
      >
        <pre className="mb-4 bg-gray-100 p-4 rounded-md overflow-x-auto whitespace-pre-wrap">
          {formattedData}
        </pre>
        <>{children}</>
      </Disclosure>
    </div>
  );
}
