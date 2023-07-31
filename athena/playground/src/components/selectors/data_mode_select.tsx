import type { DataMode } from "@/model/data_mode";

export default function DataModeSelect({
  dataMode,
  onChangeDataMode,
}: {
  dataMode: DataMode;
  onChangeDataMode: (dataMode: DataMode) => void;
}) {
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Dataset</span>
      <div className="flex flex-row mb-2">
        <button
          className={`p-2 rounded-l-md ${
            dataMode === "example"
              ? "bg-primary-500 text-white hover:bg-primary-600"
              : "bg-gray-200 text-gray-500 hover:bg-gray-300"
          }`}
          onClick={() => onChangeDataMode("example")}
        >
          Example data
        </button>
        <button
          className={`p-2 rounded-r-md ${
            dataMode === "evaluation"
              ? "bg-primary-500 text-white hover:bg-primary-600"
              : "bg-gray-200 text-gray-500 hover:bg-gray-300"
          }`}
          onClick={() => onChangeDataMode("evaluation")}
        >
          Evaluation data
        </button>
      </div>
      <p className="text-gray-500">
        Data in <code className="bg-gray-100 p-1 rounded-sm">data/{dataMode}/</code>{" "}
        directory will be used.
      </p>
    </label>
  );
}
