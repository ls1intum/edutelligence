import mysql from 'mysql2/promise';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { loadDBConfig } from './db_config.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const evaluationDirPath = path.join(__dirname, '..', 'data', 'evaluation');
const textExercisesExportQueryPath = path.join(__dirname, 'export_text_exercises.sql');

async function executeQuery(config) {
  const connection = await mysql.createConnection({
    ...config,
    multipleStatements: true,
  });
  console.log('Connected to the database!');

  try {
    const sql = await fs.promises.readFile(textExercisesExportQueryPath, 'utf8');
    const [results] = await connection.query(sql);
    const [exercises] = results.slice(-1);
    exercises.forEach(async ({ exercise_data }) => {
      const { id } = exercise_data;
      const filePath = path.join(evaluationDirPath, `exercise-${id}.json`);
      await fs.promises.writeFile(filePath, JSON.stringify(exercise_data, null, 2));
    });
    console.log(`Exported ${exercises.length} exercises to ${evaluationDirPath}`);
  } catch (err) {
    throw err;
  } finally {
    await connection.end();
  }
}

loadDBConfig().then(executeQuery).catch(console.error);
