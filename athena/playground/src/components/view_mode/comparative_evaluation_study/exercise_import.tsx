import React from "react";
import { Exercise } from "@/model/exercise";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faTrash, faPlus } from "@fortawesome/free-solid-svg-icons";

type ExerciseImportProps = {
  exercises: Exercise[];
  setExercises: (exercises: Exercise[]) => void;
  disabled: boolean;
};

export default function ExerciseImport(exerciseImportProps: ExerciseImportProps) {
  const { exercises, setExercises, disabled } = exerciseImportProps;

  const handleExerciseImport = async (fileContents: string[]) => {
    const importedExercises = fileContents.map((fileContent) => JSON.parse(fileContent) as Exercise);
    setExercises([...exercises, ...importedExercises]);
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      const fileReaders = files.map(file => {
        return new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (event) => {
            if (event.target && typeof event.target.result === "string") {
              resolve(event.target.result);
            } else {
              reject(new Error("File reading failed"));
            }
          };
          reader.readAsText(file);
        });
      });

      Promise.all(fileReaders)
        .then((fileContents) => {
          handleExerciseImport(fileContents);
        })
        .catch((error) => {
          console.error("Error importing exercises:", error);
        });
    }
    e.target.value = ""; // Reset file input
  };

  const removeExercise = (exerciseId: number) => {
    setExercises(exercises.filter((exercise) => exercise.id !== exerciseId));
  };

  return (
    <section className="flex flex-col">
      <div className="flex justify-between items-center mb-2">
        {/* Heading */}
        <span className="text-lg font-bold">Exercises</span>

        {/* Import New Exercises Button */}
        {!disabled && (
          <label className="bg-green-500 text-white rounded-md p-2 hover:bg-green-600 flex items-center gap-2 cursor-pointer">
            <FontAwesomeIcon icon={faPlus} />
            Import Exercises
            <input
              type="file"
              accept=".json"
              className="hidden"
              multiple
              onChange={onFileChange}
            />
          </label>
        )}
      </div>

      {/* List of Imported Exercises */}
      <ul className="space-y-2">
        {exercises.length === 0 ? (
          <li className="border p-2 rounded-md shadow-sm bg-gray-50 text-center">
            No exercises added! Please add exercises with submissions and categorized feedback.
          </li>
        ) : (
          exercises.map((exercise) => (
            <li key={exercise.id} className="flex justify-between items-center border p-2 rounded-md shadow-sm">
              <span>{exercise.title}</span>

              <div className="flex space-x-2">
                {!disabled && (
                  <button
                    className="bg-red-500 text-white rounded-md p-2 hover:bg-red-600"
                    onClick={() => removeExercise(exercise.id)}
                    title="Delete Exercise"
                  >
                    <FontAwesomeIcon icon={faTrash} />
                  </button>
                )}
              </div>
            </li>
          ))
        )}
      </ul>
    </section>
  );
};
