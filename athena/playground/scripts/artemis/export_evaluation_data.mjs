import mysql from 'mysql2/promise';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { loadDBConfig } from './db_config.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const evaluationOutputDirPath = path.join(__dirname, '..', '..', 'data', 'evaluation');

const text = {
  exerciseType: 'text',
  queryPath: path.join(__dirname, 'export_text_exercises.sql'),
  inputDataPath: path.join(__dirname, 'evaluation_data', 'text_exercises.json'),
}

const programming = {
  exerciseType: 'programming',
  queryPath: path.join(__dirname, 'export_programming_exercises.sql'),
  inputDataPath: path.join(__dirname, 'evaluation_data', 'programming_exercises.json'), 
}

async function exportExercises(connection, queryPath, inputDataPath, exerciseType) {
  const inputData = JSON.parse(await fs.promises.readFile(inputDataPath, 'utf8'));

  // Allows for grouping exercises
  let exerciseIds = []
  const findExerciseIds = (inputData) => {
    if (inputData.id) {
      exerciseIds.push(inputData.id)
    } else if (Array.isArray(inputData)) {
      inputData.forEach((item) => findExerciseIds(item))
    } else if (typeof inputData === 'object') {
      Object.values(inputData).forEach((item) => findExerciseIds(item))
    }
  }
  findExerciseIds(inputData);

  if (!exerciseIds.length) {
    console.log(`No ${exerciseType} exercises to export in ${inputDataPath}`);
    return;
  }
  console.log(`Found ${exerciseIds.length} ${exerciseType} exercises to export in ${inputDataPath}`);

  let sql = await fs.promises.readFile(queryPath, 'utf8');
  const placeholders = exerciseIds.map(() => '?').join(',');
  sql = sql.replace(":exercise_ids", `(${placeholders})`);

  try {
    console.log(`Exporting ${exerciseType} exercises...`);
    const [results] = await connection.query(sql, exerciseIds);
    const [exercises] = results.slice(-1);
    exercises.forEach(async ({ exercise_data }) => {
      const { id } = exercise_data;
      const filePath = path.join(evaluationOutputDirPath, `exercise-${id}.json`);
      await fs.promises.writeFile(filePath, JSON.stringify(exercise_data, null, 2));
    });
    console.log(`Exported ${exercises.length} ${exerciseType} exercises to ${evaluationOutputDirPath}`);
  } catch (err) {
    throw err;
  }
}

async function executeQuery(config) {
  const connection = await mysql.createConnection({
    ...config,
    multipleStatements: true,
  });
  console.log('Connected to the database!');

  try {
    await exportExercises(connection, text.queryPath, text.inputDataPath, text.exerciseType);
    await exportExercises(connection, programming.queryPath, programming.inputDataPath, programming.exerciseType);
    console.log('Done!');
  } catch (err) {
    throw err;
  } finally {
    await connection.end();
  }
}

loadDBConfig().then(executeQuery).catch(console.error);
