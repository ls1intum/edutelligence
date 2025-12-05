import { useState } from "react";
import { v4 as uuidv4 } from 'uuid';
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEdit, faPlus, faSave, faTrash } from "@fortawesome/free-solid-svg-icons";
import ReactMarkdown from 'react-markdown';
import rehypeRaw from "rehype-raw";
import { Metric } from "@/model/metric";

type MetricsFormProps = {
  metrics: Metric[];
  setMetrics: (metrics: Metric[]) => void;
  disabled: boolean;
};

export default function MetricsForm(metricsFormProps: MetricsFormProps) {
  const { metrics, setMetrics, disabled } = metricsFormProps;

  const [editIndex, setEditIndex] = useState<number | null>(null);
  const [editingMetric, setEditingMetric] = useState<Metric>({
    id: "",
    title: "",
    summary: "",
    description: "",
  });
  const [newMetric, setNewMetric] = useState<Metric>({
    id: "",
    title: "",
    summary: "",
    description: "",
  });

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    isEditing: boolean = false
  ) => {
    const { name, value } = e.target;
    if (isEditing) {
      setEditingMetric((prevMetric) => ({
        ...prevMetric,
        [name]: value,
      }));
    } else {
      setNewMetric((prevMetric) => ({
        ...prevMetric,
        [name]: value,
      }));
    }
  };

  const addMetric = () => {
    if (!newMetric.title.trim() || !newMetric.summary.trim() || !newMetric.description.trim()) {
      return;
    }

    const metricWithId = { ...newMetric, id: uuidv4() };
    setMetrics([...metrics, metricWithId]);
    setNewMetric({ id: "", title: "", summary: "", description: "" }); // Reset form
  };

  const startEditMetric = (index: number) => {
    setEditIndex(index);
    setEditingMetric(metrics[index]);
  };

  const saveMetric = () => {
    if (editIndex !== null) {
      const updatedMetrics = metrics.map((metric, index) =>
        index === editIndex ? editingMetric : metric
      );
      setMetrics(updatedMetrics);
      setEditIndex(null); // Exit editing mode
    }
  };

  const removeMetric = (index: number) => {
    setMetrics(metrics.filter((_, i) => i !== index));
  };

  const inputDisabledStyle = disabled
    ? "bg-gray-100 text-gray-500 cursor-not-allowed"
    : "";

  const buttonDisabledStyle = disabled ? "hidden" : "";

  return (
    <section className="flex flex-col">
      <span className="text-lg font-bold mb-2">Metrics</span>
      <div className="flex flex-col gap-4">

        {/* List of Metrics */}
        {metrics.map((metric, index) => (
          <div
            key={metric.id}
            className="flex justify-between items-start border p-4 rounded-md shadow-sm"
          >
            {editIndex === index ? (
              <div className="space-y-2 flex-1">
                <input
                  type="text"
                  name="title"
                  value={editingMetric.title}
                  onChange={(e) => handleChange(e, true)}
                  className={`border border-gray-300 rounded-md p-2 w-full ${inputDisabledStyle}`}
                  placeholder="Metric Title"
                  disabled={disabled}
                />
                <input
                  type="text"
                  name="summary"
                  value={editingMetric.summary}
                  onChange={(e) => handleChange(e, true)}
                  className={`border border-gray-300 rounded-md p-2 w-full ${inputDisabledStyle}`}
                  placeholder="Metric Summary"
                  disabled={disabled}
                />
                <textarea
                  name="description"
                  value={editingMetric.description}
                  onChange={(e) => handleChange(e, true)}
                  className={`border border-gray-300 rounded-md p-2 w-full ${inputDisabledStyle}`}
                  rows={2}
                  placeholder="Metric Description"
                  disabled={disabled}
                />
                <button
                  onClick={saveMetric}
                  className={`bg-green-500 text-white rounded-md p-2 hover:bg-green-600 flex items-center gap-2 ${buttonDisabledStyle}`}
                  disabled={disabled}
                >
                  <FontAwesomeIcon icon={faSave} />
                  Save
                </button>
              </div>
            ) : (
              <div className="space-y-2 flex-1">
                <input
                  type="text"
                  value={metric.title}
                  readOnly
                  className={`border border-gray-300 rounded-md p-2 w-full ${inputDisabledStyle}`}
                  placeholder="Metric Title"
                />
                <input
                  type="text"
                  value={metric.summary}
                  readOnly
                  className={`border border-gray-300 rounded-md p-2 w-full ${inputDisabledStyle}`}
                  placeholder="Metric Summary"
                />
                <div className="border border-gray-300 rounded-md p-2 w-full">
                  <div className="prose-sm">
                    <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                      {metric.description}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            )}

            {/* Buttons for Edit and Remove */}
            <div className="flex flex-col gap-2 items-center ml-4">
              <button
                onClick={() => startEditMetric(index)}
                className={`bg-gray-500 text-white rounded-md p-2 hover:bg-gray-600 flex items-center gap-2 ${buttonDisabledStyle}`}
                disabled={disabled}
              >
                <FontAwesomeIcon icon={faEdit} />
              </button>
              <button
                onClick={() => removeMetric(index)}
                className={`bg-red-500 text-white rounded-md p-2 hover:bg-red-600 flex items-center gap-2 ${buttonDisabledStyle}`}
                disabled={disabled}
              >
                <FontAwesomeIcon icon={faTrash} />
              </button>
            </div>
          </div>
        ))}

        {/* New Metric Form */}
        {!disabled && (
          <div className="flex flex-col gap-2 border p-4 rounded-md shadow-sm">
            <div>
              <label className="block text-sm">
                <span className="text-gray-700">Title</span>
                <input
                  type="text"
                  name="title"
                  value={newMetric.title}
                  onChange={(e) => handleChange(e, false)}
                  className={`mt-1 block w-full border border-gray-300 rounded-md p-2 ${inputDisabledStyle}`}
                  placeholder="Enter a title for the new metric."
                  disabled={disabled}
                />
              </label>
            </div>

            <div>
              <label className="block text-sm">
                <span className="text-gray-700">Summary</span>
                <input
                  type="text"
                  name="summary"
                  value={newMetric.summary}
                  onChange={(e) => handleChange(e, false)}
                  className={`mt-1 block w-full border border-gray-300 rounded-md p-2 ${inputDisabledStyle}`}
                  placeholder="Enter a short statement that the expert can agree or disagree with."
                  disabled={disabled}
                />
              </label>
            </div>

            <div>
              <label className="block text-sm">
                <span className="text-gray-700">Description</span>
                <textarea
                  name="description"
                  value={newMetric.description}
                  onChange={(e) => handleChange(e, false)}
                  className={`mt-1 block w-full border border-gray-300 rounded-md p-2 ${inputDisabledStyle}`}
                  rows={3}
                  placeholder="You can provide a detailed description of the metric here. You can use markdown to format the text."
                  disabled={disabled}
                />
              </label>
            </div>

            <div className="flex gap-2">
              <button
                onClick={addMetric}
                className={`bg-green-500 text-white rounded-md p-2 hover:bg-green-600 flex items-center gap-2 ${buttonDisabledStyle}`}
              >
                <FontAwesomeIcon icon={faPlus} />
                Add Metric
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
