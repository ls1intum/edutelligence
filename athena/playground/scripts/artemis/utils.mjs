import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const evaluationOutputDirPath = path.join(
  __dirname,
  "..",
  "..",
  "data",
  "evaluation"
);

export const text = {
  exerciseType: "text",
  queryPath: path.join(__dirname, "export_text_exercises.sql"),
  inputDataPath: path.join(__dirname, "evaluation_data", "text_exercises.json"),
};

export const modeling = {
  exerciseType: "modeling",
  queryPath: path.join(__dirname, "export_modeling_exercises.sql"),
  inputDataPath: path.join(__dirname, "evaluation_data", "modeling_exercises.json"),
};

export const programming = {
  exerciseType: "programming",
  queryPath: path.join(__dirname, "export_programming_exercises.sql"),
  inputDataPath: path.join(
    __dirname,
    "evaluation_data",
    "programming_exercises.json"
  ),
};

export function findExerciseIds(inputData, acc) {
  acc = acc || [];
  if (inputData.id) {
    acc.push(inputData.id);
  } else if (Array.isArray(inputData)) {
    inputData.forEach((item) => findExerciseIds(item, acc));
  } else if (typeof inputData === "object") {
    Object.values(inputData).forEach((item) => findExerciseIds(item, acc));
  }
  return acc;
};
