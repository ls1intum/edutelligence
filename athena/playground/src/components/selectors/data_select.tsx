import { Mode } from "@/model/mode";

export default function DataSelect({
  mode,
  onChangeMode,
}: {
  mode: Mode;
  onChangeMode: (mode: Mode) => void;
}) {
  return (
    <label className="flex flex-col">
      <span className="text-lg font-bold">Dataset</span>
      <div className="flex flex-row mb-2">
        <button
          className={`p-2 rounded-l-md ${
            mode === "example"
              ? "bg-primary-500 text-white hover:bg-primary-600"
              : "bg-gray-200 text-gray-500 hover:bg-gray-300"
          }`}
          onClick={() => onChangeMode("example")}
        >
          Example data
        </button>
        <button
          className={`p-2 rounded-r-md ${
            mode === "evaluation"
              ? "bg-primary-500 text-white hover:bg-primary-600"
              : "bg-gray-200 text-gray-500 hover:bg-gray-300"
          }`}
          onClick={() => onChangeMode("evaluation")}
        >
          Evaluation data
        </button>
      </div>
      <p className="text-gray-500">
        Data in <code className="bg-gray-100 p-1 rounded-sm">data/{mode}/</code>{" "}
        directory will be used.
      </p>
    </label>
  );
}
