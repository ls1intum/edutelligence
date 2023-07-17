import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from 'url';
import inquirer from "inquirer";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const configPath = path.join(__dirname, "db_config.json");

const defaultConfig = {
  host: "127.0.0.1",
  port: 3306,
  user: "root",
  password: "",
  database: "anonymized_artemis",
};

export async function loadDBConfig() {
  try {
    const data = await fs.readFile(configPath, "utf8");
    const config = JSON.parse(data);
    console.log(`Previous config found (${configPath}):`, config);
    const { usePrevious } = await inquirer.prompt([
      {
        type: "confirm",
        name: "usePrevious",
        message: "Do you want to use the previous config?",
        default: true,
      },
    ]);
    if (usePrevious) return config;
  } catch (err) {
    console.log("No previous config found. Enter new details:");
  }
  return await promptForConfig();
}

async function promptForConfig() {
  const questions = [
    {
      type: "input",
      name: "host",
      message: `Enter host:`,
      default: defaultConfig.host,
    },
    {
      type: "input",
      name: "port",
      message: `Enter port:`,
      default: defaultConfig.port,
    },
    {
      type: "input",
      name: "user",
      message: `Enter username:`,
      default: defaultConfig.user,
    },
    {
      type: "password",
      name: "password",
      message: `Enter password:`,
      default: defaultConfig.password,
    },
    {
      type: "input",
      name: "database",
      message: `Enter database:`,
      default: defaultConfig.database,
    },
  ];

  const config = await inquirer.prompt(questions);

  try {
    await fs.writeFile(configPath, JSON.stringify(config, null, 2));
    console.log(`Config saved to ${configPath}`);
  } catch (err) {
    console.error("Error saving config:", err);
  }

  return config;
}
