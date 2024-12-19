import { useEffect, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { downloadJSONFile } from "@/helpers/download";
import { twMerge } from "tailwind-merge";
import MetricsForm from "@/components/view_mode/evaluation_mode/expert_evaluation/metrics_form";
import { ExpertEvaluationConfig } from "@/model/expert_evaluation_config";
import EvaluationConfigSelector from "@/components/selectors/evaluation_config_selector";
import {
  EvaluationManagementExportImport
} from "@/components/view_mode/evaluation_mode/expert_evaluation/evaluation_management_export_import";
import {
  fetchAllExpertEvaluationConfigs,
  saveExpertEvaluationConfig as externalSaveExpertEvaluationConfig
} from "@/hooks/playground/expert_evaluation_config";
import ExpertLinks from "@/components/view_mode/evaluation_mode/expert_evaluation/expert_links";
import ExerciseImport from "@/components/view_mode/evaluation_mode/expert_evaluation/exercise_import";
import useDownloadExpertEvaluationData from "@/hooks/playground/expert_evaluation";

const createNewEvaluationConfig = (name = ""): ExpertEvaluationConfig => ({
  type: "evaluation_config",
  id: "new",
  name,
  started: false,
  creationDate: new Date(),
  metrics: [],
  exercises: [],
  expertIds: [],
});

export default function EvaluationManagement() {
  const [expertEvaluationConfigs, setExpertEvaluationConfigs] = useState<ExpertEvaluationConfig[]>([]);
  const [selectedConfig, setSelectedConfig] = useState<ExpertEvaluationConfig>(createNewEvaluationConfig());
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const dataMode = "expert_evaluation";

  useEffect(() => {
    const fetchData = async () => {
      const savedConfigs = await fetchAllExpertEvaluationConfigs(dataMode);
      setExpertEvaluationConfigs(savedConfigs);
    };
    fetchData();
  }, []);

  const handleSelectConfig = (id: string) => {
    if (id === "new") {
      setSelectedConfig(createNewEvaluationConfig());
    } else {
      const existingConfig = expertEvaluationConfigs.find((config) => config.id === id);
      if (existingConfig) {
        setSelectedConfig(existingConfig);
      }
    }
    setHasUnsavedChanges(false);
  };

  const updateSelectedConfig = (updatedFields: Partial<ExpertEvaluationConfig>): ExpertEvaluationConfig => {
    const isUpdatingOnlyExpertIds =
      Object.keys(updatedFields).length === 1 && updatedFields.hasOwnProperty('expertIds');
    const newConfig = { ...selectedConfig, ...updatedFields };

    if (!selectedConfig.started || isUpdatingOnlyExpertIds) {
      setSelectedConfig(newConfig);
      setHasUnsavedChanges(true);
    }

    return newConfig;
  };

  const saveExpertEvaluationConfig = (configToSave = selectedConfig, isAnonymize = false) => {
    const isNewConfig = configToSave.id === "new";
    const newConfig = isNewConfig ? { ...configToSave, id: uuidv4() } : configToSave;
    setExpertEvaluationConfigs((prevConfigs) => {
      const existingIndex = prevConfigs.findIndex((config) => config.id === newConfig.id);
      if (existingIndex !== -1) {
        const updatedConfigs = [...prevConfigs];
        updatedConfigs[existingIndex] = newConfig;
        return updatedConfigs;
      } else {
        return [...prevConfigs, newConfig];
      }
    });

    setSelectedConfig(newConfig);
    externalSaveExpertEvaluationConfig(dataMode, newConfig, isAnonymize);
    setHasUnsavedChanges(false);
  };

  const handleExport = () => {
    downloadJSONFile(`evaluation_config_${selectedConfig.name}_${selectedConfig.id}`, selectedConfig);
  };

  const handleImport = async (fileContent: string) => {
    const importedConfig = JSON.parse(fileContent) as ExpertEvaluationConfig;
    if (importedConfig.type !== "evaluation_config") {
      alert("Invalid config type");
      return;
    }
    importedConfig.id = "new";
    importedConfig.creationDate = new Date();
    importedConfig.started = false;
    importedConfig.expertIds = [];
    setSelectedConfig(importedConfig);
  };

  const { mutate: downloadEvaluationData, isLoading: isExporting } = useDownloadExpertEvaluationData({
    onSuccess: (blob: Blob) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;
      a.download = `evaluation_${selectedConfig.id}.zip`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
    },
    onError: (error) => {
      console.error("Download failed:", error.message);
      alert("An error occurred during download. Please try again later.");
    },
  });

  const startEvaluation = () => {
    if (confirm("Are you sure you want to start the evaluation? Once started, you can add new expert links but no other changes can be made to the configuration!")) {
      const updatedConfig = updateSelectedConfig({ started: true });
      saveExpertEvaluationConfig(updatedConfig, true);
    }
  };

  const resetChanges = () => {
    if (selectedConfig.id === "new") {
      setSelectedConfig(createNewEvaluationConfig());
    } else {
      const existingConfig = expertEvaluationConfigs.find((config) => config.id === selectedConfig.id);
      if (existingConfig) {
        setSelectedConfig(existingConfig);
      }
    }
    setHasUnsavedChanges(false);
  };

  const inputDisabledStyle = selectedConfig.started
    ? "bg-gray-100 text-gray-500 cursor-not-allowed"
    : "";

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-4">
      <div className="flex flex-row justify-between items-center">
        <h3 className="text-2xl font-bold">Manage Evaluations</h3>
        <EvaluationManagementExportImport
          definedExpertEvaluationConfig={selectedConfig}
          handleExport={handleExport}
          handleImport={handleImport}
        />
      </div>

      <EvaluationConfigSelector
        selectedConfigId={selectedConfig.id}
        setSelectedConfigId={handleSelectConfig}
        expertEvaluationConfigs={expertEvaluationConfigs}
      />

      <label className="flex flex-col">
        <span className="text-lg font-bold mb-2">Evaluation Name</span>
        <input
          type="text"
          placeholder="Enter a name for the evaluation."
          className={`border border-gray-300 rounded-md p-2 ${inputDisabledStyle}`}
          value={selectedConfig.name}
          onChange={(e) => updateSelectedConfig({ name: e.target.value })}
          disabled={selectedConfig.started}
        />
      </label>

      <ExerciseImport
        exercises={selectedConfig.exercises}
        setExercises={(newExercises) => updateSelectedConfig({ exercises: newExercises })}
        disabled={selectedConfig.started}
      />

      <MetricsForm
        metrics={selectedConfig.metrics}
        setMetrics={(newMetrics) => updateSelectedConfig({ metrics: newMetrics })}
        disabled={selectedConfig.started}
      />

      <ExpertLinks
        expertIds={selectedConfig.expertIds!}
        setExpertIds={(newExpertIds) => updateSelectedConfig({ expertIds: newExpertIds })}
        configId={selectedConfig.id}
        started={selectedConfig.started}
      />

      <div className="flex flex-row gap-2 mt-4">
        <button
          className={twMerge(
            selectedConfig.id === "new" ? "bg-blue-500 hover:bg-blue-600" : "bg-green-500 hover:bg-green-600",
            "text-white rounded-md p-2",
            !hasUnsavedChanges ? "opacity-60 cursor-not-allowed" : ""
          )}
          onClick={() => saveExpertEvaluationConfig(selectedConfig)}
          disabled={!hasUnsavedChanges}
        >
          {selectedConfig.id === "new" ? "Define Experiment" : "Save Changes"}
        </button>

        <button
          className={twMerge(
            selectedConfig.id === "new"
              ? "bg-red-500 hover:bg-red-600"
              : "bg-gray-500 hover:bg-gray-600",
            "text-white rounded-md p-2",
            !hasUnsavedChanges ? "opacity-60 cursor-not-allowed" : ""
          )}
          onClick={resetChanges}
          disabled={!hasUnsavedChanges}
        >
          {selectedConfig.id === "new" ? "Cancel" : "Reset Changes"}
        </button>

        {selectedConfig.started && (
          <button
            className={twMerge(
              "bg-blue-500 text-white rounded-md p-2 hover:bg-blue-600",
              isExporting ? "opacity-75 cursor-not-allowed" : ""
            )}
            onClick={() => downloadEvaluationData({ configId: selectedConfig.id })}
            disabled={isExporting}
          >
            {isExporting ? "Downloading..." : "Download Results"}
          </button>
        )}

        {selectedConfig.id !== "new" && !selectedConfig.started && (
          <button
            className="bg-green-500 text-white rounded-md p-2 hover:bg-green-600"
            onClick={startEvaluation}
          >
            Start Evaluation
          </button>
        )}
      </div>
    </div>
  );
}
