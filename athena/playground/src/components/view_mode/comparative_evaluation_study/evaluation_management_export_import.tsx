import React from "react";

type EvaluationManagementExportImportProps = {
  definedExpertEvaluationConfig: any;
  handleExport: () => void;
  handleImport: (fileContent: string) => void;
};

export function EvaluationManagementExportImport(evaluationManagementExportImportProps: EvaluationManagementExportImportProps) {
  const { definedExpertEvaluationConfig, handleExport, handleImport } = evaluationManagementExportImportProps;

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = (e) => {
        if (e.target && typeof e.target.result === "string") {
          handleImport(e.target.result);
        }
      };
      reader.readAsText(file);
    }
    e.target.value = ""; // Reset file input
  };

  return (
    <div className="flex flex-row">
      <button
        disabled={!definedExpertEvaluationConfig}
        className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed"
        onClick={handleExport}
      >
        Export
      </button>
      <label
        className="rounded-md p-2 cursor-pointer text-primary-500 hover:text-primary-600 hover:bg-gray-100">
        Import
        <input className="hidden" type="file" accept=".json" onChange={onFileChange} />
      </label>
    </div>
  );
}
