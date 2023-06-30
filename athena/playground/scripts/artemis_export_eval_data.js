const mysql = require('mysql2/promise');
const fs = require('fs').promises;
const path = require('path');

const { loadDBConfig } = require('./db_config.mjs');

const evaluationDirPath = path.join(__dirname, '..', 'data', 'evaluation');
const textExercisesExportQueryPath = path.join(__dirname, 'export_text_exercises.sql');

async function executeQuery(config) {
  const connection = await mysql.createConnection({
    ...config,
    multipleStatements: true,
  });
  console.log('Connected to the database!');

  try {
    const sql = await fs.readFile(textExercisesExportQueryPath, 'utf8');
    const [results] = await connection.query(sql);
    const [exercises] = results.slice(-1);
    exercises.forEach(({ exercise_data }) => {
      const { id } = exercise_data;
      const filePath = path.join(evaluationDirPath, `exercise-${id}.json`);
      fs.writeFile(filePath, JSON.stringify(exercise_data, null, 2));
    });
    console.log(`Exported ${exercises.length} exercises to ${evaluationDirPath}`);
  } catch (err) {
    throw err;
  } finally {
    connection.end();
    process.exit();
  }
}

loadDBConfig().then(executeQuery).catch(console.error);
