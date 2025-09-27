import fs from "fs";
import path from "path";

import { programming, evaluationOutputDirPath, findExerciseIds } from "./utils.mjs";

// Find all exercise-*.json files in the evaluation output directory
const exerciseFilePaths = fs
  .readdirSync(evaluationOutputDirPath)
  .filter((fileName) => fileName.match(/^exercise-\d+\.json$/))
  .map((fileName) => path.join(evaluationOutputDirPath, fileName));

// Read all exercise-*.json files and filter out the programming exercises
const exercises = exerciseFilePaths.flatMap((filePath) => {
  const fileContent = fs.readFileSync(filePath, "utf8");
  const exercise = JSON.parse(fileContent);
  if (exercise.type === "programming") {
    return [exercise];
  } else {
    return [];
  }
})

let successfulExercises = 0;

// Link the programming exercises with their submissions and materials
for (let exercise of exercises) {
  const exercisePath = path.join(evaluationOutputDirPath, `exercise-${exercise.id}`);
  if (!fs.existsSync(exercisePath)) {
    console.log(`Exercise ${exercise.id} has no directory at ${exercisePath}`);
    continue;
  }

  if (!fs.existsSync(path.join(exercisePath, "solution"))) {
    console.log(`Exercise ${exercise.id} has no solution at ${exercisePath}/solution`);
    exercise.solution_repository_uri = null;
  } else {
    exercise.solution_repository_uri = `{{exerciseDataUrl}}/solution`;
  }

  if (!fs.existsSync(path.join(exercisePath, "template"))) {
    console.log(`Exercise ${exercise.id} has no template at ${exercisePath}/template`);
    exercise.template_repository_uri = null;
  } else {
    exercise.template_repository_uri = `{{exerciseDataUrl}}/template`;
  }

  if (!fs.existsSync(path.join(exercisePath, "tests"))) {
    console.log(`Exercise ${exercise.id} has no tests at ${exercisePath}/tests`);
    exercise.tests_repository_uri = null;
  } else {
    exercise.tests_repository_uri = `{{exerciseDataUrl}}/tests`;
  }

  const submissionsPath = path.join(exercisePath, "submissions");
  exercise.submissions = exercise.submissions.map((submission) => {
    const submissionPath = path.join(submissionsPath, `${submission.id}`);
    if (!fs.existsSync(submissionPath)) {
      console.log(`Submission ${submission.id} has no directory at ${submissionPath}`);
      submission.repository_uri = null;
    } else {
      submission.repository_uri = `{{exerciseDataUrl}}/submissions/${submission.id}`;
    }
    return submission;
  });

  fs.writeFileSync(
    path.join(evaluationOutputDirPath, `exercise-${exercise.id}.json`),
    JSON.stringify(exercise, null, 2)
  );
  console.log(`Linked exercise ${exercise.id} with its submissions and materials`);
  successfulExercises += 1;
};

console.log(`Linked ${successfulExercises} of ${exercises.length} programming exercises`);
