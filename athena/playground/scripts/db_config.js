const fs = require("fs").promises;
const readline = require("readline");
const path = require("path");

const configPath = path.join(__dirname, "db_config.json");

const defaultConfig = {
  host: "127.0.0.1",
  user: "root",
  password: "",
  database: "anonymized_artemis",
};

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

async function loadDBConfig() {
  try {
    const data = await fs.readFile(configPath, "utf8");
    const config = JSON.parse(data);
    console.log(`Previous config found (${configPath}):`, config);
    const answer = await askQuestion(
      "Do you want to use the previous config? (yes/no) "
    );
    if (answer.toLowerCase() === "yes" || answer.toLowerCase() === "y") {
      return config;
    }
  } catch (err) {
    console.log("No previous config found. Enter new details:");
  }
  return await promptForConfig();
}

function askQuestion(query) {
  return new Promise((resolve) => rl.question(query, resolve));
}

async function promptForConfig() {
  const host =
    (await askQuestion(`Enter host: (default: "${defaultConfig.host}")`)) ||
    defaultConfig.host;
  const user =
    (await askQuestion(
      `Enter username: (default: "${defaultConfig.user}")`
    )) || defaultConfig.user;
  const password =
    (await askQuestion(
      `Enter password: (default: "${defaultConfig.password}")`
    )) || defaultConfig.password;
  const database =
    (await askQuestion(
      `Enter database: (default: "${defaultConfig.database}")`
    )) || defaultConfig.database;

  const config = { host, user, password, database };

  try {
    await fs.writeFile(configPath, JSON.stringify(config));
    console.log(`Config saved to ${configPath}`);
  } catch (err) {
    console.log("Error saving config:", err);
  }

  return config;
}

module.exports = {
  loadDBConfig,
};
