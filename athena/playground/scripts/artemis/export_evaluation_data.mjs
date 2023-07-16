import mysql from "mysql2/promise";
import fs from "fs";
import path from "path";
import { loadDBConfig } from "./db_config.mjs";

import { text, programming, findExerciseIds, evaluationOutputDirPath } from "./utils.mjs";

/**
 * Exports the exercises from the Artemis database to JSON files for the playground.
 * 
 * @param {mysql.Connection} connection - The connection to the database.
 * @param {string} queryPath - The path to the SQL query to execute, doing the export.
 * @param {string} inputDataPath - The path to the JSON file containing the input data for the query, i.e. the exercise IDs.
 * @param {string} exerciseType - The type of the exercises to export, i.e. "text" or "programming".
 */
async function exportExercises(
  connection,
  queryPath,
  inputDataPath,
  exerciseType
) {
  const inputData = JSON.parse(
    await fs.promises.readFile(inputDataPath, "utf8")
  );

  let exerciseIds = findExerciseIds(inputData);
  if (!exerciseIds.length) {
    console.warn(`No ${exerciseType} exercises to export in ${inputDataPath}`);
    return;
  }
  console.log(`Found ${exerciseIds.length} ${exerciseType} exercises to export in ${inputDataPath}`);

  let sql = await fs.promises.readFile(queryPath, "utf8");
  const placeholders = exerciseIds.map(() => "?").join(",");
  sql = sql.replace(":exercise_ids", `(${placeholders})`);

  try {
    console.log(`Exporting ${exerciseType} exercises...`);
    const [results] = await connection.query(sql, exerciseIds);
    const [exercises] = results.slice(-1);
    exercises.forEach(async ({ exercise_data }) => {
      const { id } = exercise_data;
      const filePath = path.join(
        evaluationOutputDirPath,
        `exercise-${id}.json`
      );
      await fs.promises.writeFile(
        filePath,
        JSON.stringify(exercise_data, null, 2)
      );
    });
    console.log(
      `Exported ${exercises.length} ${exerciseType} exercises to ${evaluationOutputDirPath}`
    );
  } catch (err) {
    throw err;
  }
}

async function executeQuery(config) {
  const connection = await mysql.createConnection({
    ...config,
    multipleStatements: true,
  });
  console.log("Connected to the database!");

  try {
    await exportExercises(
      connection,
      text.queryPath,
      text.inputDataPath,
      text.exerciseType
    );
    await exportExercises(
      connection,
      programming.queryPath,
      programming.inputDataPath,
      programming.exerciseType
    );
    console.log(
      "\nNote: For programming exercises you have to still export the materials and submissions and link them using another two npm scripts."
    );
    console.log("Done!");
  } catch (err) {
    throw err;
  } finally {
    await connection.end();
  }
}

loadDBConfig().then(executeQuery).catch(console.error);
