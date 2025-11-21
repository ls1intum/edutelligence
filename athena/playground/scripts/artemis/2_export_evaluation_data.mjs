import inquirer from "inquirer";
import mysql from "mysql2/promise";
import fs from "fs";
import path from "path";
import { loadDBConfig } from "./db_config.mjs";

import { text, programming, findExerciseIds, evaluationOutputDirPath, modeling } from "./utils.mjs";

/**
 * Exports exercises of a certain type from the Artemis database to JSON files for the playground.
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

  // The query is a template string, so we have to replace the placeholders with the actual values.
  // We use the exercise IDs as placeholders, so we have to generate the sa
  let sql = await fs.promises.readFile(queryPath, "utf8");
  const placeholders = exerciseIds.map(() => "?").join(",");
  sql = sql.replace(":exercise_ids", `(${placeholders})`);

  try {
    console.log(`Exporting ${exerciseType} exercises, this may take a while...`);
    const [results] = await connection.query(sql, exerciseIds);
    const [exercises] = results.slice(-1);
    await Promise.all(exercises.map(async ({ exercise_data }) => {
      const { id } = exercise_data;
      const filePath = path.join(
        evaluationOutputDirPath,
        `exercise-${id}.json`
      );
      await fs.promises.writeFile(
        filePath,
        JSON.stringify(exercise_data, null, 2)
      );
    }));
    console.log(`Exported ${exercises.length} ${exerciseType} exercises to ${evaluationOutputDirPath}`);
  } catch (err) {
    throw err;
  }
}


/**
 * Exports all exercises from the Artemis database to JSON files for the playground.
 * 
 * @param config - The database config (host, port, user, password, database)
 */
async function exportAllExercises(config) {
  const connection = await mysql.createConnection({
    ...config,
    multipleStatements: true,
  });
  console.log("Connected to the database!");

  const { exerciseTypes } = await inquirer.prompt({
    type: "checkbox",
    name: "exerciseTypes",
    message: "Which exercise types do you want to export?",
    choices: [{
      name: "Text exercises",
      value: "text",
    }, {
      name: "Modeling exercises",
      value: "modeling",
    }, {
      name: "Programming exercises",
      value: "programming",
    }],
  });

  if (!exerciseTypes.length) {
    console.warn("No exercise types selected, aborting!");
    return;
  }

  try {
    if (exerciseTypes.includes("text")) {
      // Export text exercises
      await exportExercises(
        connection,
        text.queryPath,
        text.inputDataPath,
        text.exerciseType
      );
    }

    if (exerciseTypes.includes("modeling")) {
      // Export modeling exercises
      await exportExercises(
        connection,
        modeling.queryPath,
        modeling.inputDataPath,
        modeling.exerciseType
      );
    }

    if (exerciseTypes.includes("programming")) {
      // Export programming exercises
      await exportExercises(
        connection,
        programming.queryPath,
        programming.inputDataPath,
        programming.exerciseType
      );
      console.log("\nNote: Repositories for programming exercises are not exported, you have to use the corresponding script to download them, and then use the linking script to link them to the exercises.");
    }
    console.log("Done!");
  } catch (err) {
    throw err;
  } finally {
    await connection.end();
  }
}

loadDBConfig().then(exportAllExercises).catch(console.error);
