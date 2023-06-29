const mysql = require('mysql2/promise');
const readline = require('readline');
const fs = require('fs').promises;
const path = require('path');

const configPath = path.join(__dirname, '.config.json');
const evaluationDirPath = path.join(__dirname, '..', 'data', 'evaluation');

const textExercisesExportQueryPath = path.join(__dirname, 'export_text_exercises.sql');

const defaultConfig = {
  host: '127.0.0.1',
  user: 'root',
  password: '',
  database: 'anonymized_artemis',
};

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

async function loadConfig() {
  try {
    const data = await fs.readFile(configPath, 'utf8');
    const config = JSON.parse(data);
    console.log('Previous config found (.config.json): ', config);
    const answer = await askQuestion('Do you want to use the previous config? (yes/no) ');
    if (answer.toLowerCase() === 'yes') {
      return config;
    }
  } catch (err) {
    console.log('No previous config found. Enter new details:');
  }
  return await promptForConfig();
}

function askQuestion(query) {
  return new Promise((resolve) => rl.question(query, resolve));
}

async function promptForConfig() {
  const host = await askQuestion(`Enter host: (default: "${defaultConfig.host}") `) || defaultConfig.host;
  const user = await askQuestion(`Enter username: (default: "${defaultConfig.user}") `) || defaultConfig.user;
  const password = await askQuestion(`Enter password: (default: "${defaultConfig.password}") `) || defaultConfig.password;
  const database = await askQuestion(`Enter database: (default: "${defaultConfig.database}") `) || defaultConfig.database;

  const config = { host, user, password, database };

  try {
    await fs.writeFile(configPath, JSON.stringify(config));
    console.log('Config saved to ".config.json".');
  } catch (err) {
    console.log('Error saving config: ', err);
  }

  return config;
}

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
    rl.close();
  }
}

loadConfig().then(executeQuery).catch(console.error);
