import mysql from "mysql2/promise";
import readline from "readline";
import fs from "fs";
import inquirer from "inquirer";
import { loadDBConfig } from "./db_config.mjs";

// To display elapsed time in HH:MM:SS format
function formatTime(seconds) {
  return new Date(seconds * 1000).toISOString().substr(11, 8);
}

async function setupDatabase(config) {
  const connection = await mysql.createConnection({
    host: config.host,
    user: config.user,
    password: config.password,
    multipleStatements: true,
  });
  console.log("Connected to the database!");

  const [results] = await connection.query(
    `SHOW DATABASES LIKE '${config.database}';`
  );
  if (results.length > 0) {
    const { answer } = await inquirer.prompt([
      {
        type: "confirm",
        name: "answer",
        message: `Database "${config.database}" already exists. Do you want to drop it and recreate it?`,
        default: false,
      },
    ]);

    if (answer) {
      const { confirm } = await inquirer.prompt([
        {
          type: "input",
          name: "confirm",
          message: `Are you sure? This will delete all data in the database "${config.database}"!\nPlease type "DELETE ${config.database}" to confirm:`,
        },
      ]);
      if (confirm !== `DELETE ${config.database}`) {
        console.log("Aborting.");
        process.exit();
      }
      await connection.query(`DROP DATABASE ${config.database};`);
      await connection.query(`CREATE DATABASE ${config.database};`);
    } else {
      const { abort } = await inquirer.prompt([
        {
          type: "confirm",
          name: "abort",
          message: `Do you want to abort?`,
          default: true,
        },
      ]);
      if (abort) {
        console.log("Aborting.");
        process.exit();
      }
    }
  } else {
    await connection.query(`CREATE DATABASE ${config.database};`);
  }

  await connection.changeUser({ database: config.database });
  return connection;
}

async function loadDBDump(config) {
  const connection = await setupDatabase(config);

  const { dumpPath } = await inquirer.prompt([
    {
      type: "input",
      name: "dumpPath",
      message: "Enter path to database dump:",
    },
  ]);

  const [rows] = await connection.query(
    "SHOW VARIABLES LIKE 'max_allowed_packet';"
  );
  if (rows.length !== 0 && rows[0].Value !== null) {
    const currentMaxAllowedPacket = rows[0].Value;
    console.log(
      `Current max_allowed_packet is set to ${currentMaxAllowedPacket} bytes.`
    );
    if (currentMaxAllowedPacket < 268435456) {
      // Set max_allowed_packet to 256MB
      // This can probably be removed in the future. The text_cluster table seems to be the problem.
      // We will drop it later anyway.
      await connection.query(`SET GLOBAL max_allowed_packet=268435456;`);
      console.log(
        `Set max_allowed_packet to 256MB to allow loading the database dump.`
      );

      // Confirm that the value was set correctly
      const [rows] = await connection.query(
        "SHOW VARIABLES LIKE 'max_allowed_packet';"
      );
      console.log(`max_allowed_packet is now set to ${rows[0].Value} bytes.`);
    }
  }

  try {
    console.log("Loading database dump this may take a while (+30-60min)...");

    const rl = readline.createInterface({
      input: fs.createReadStream(dumpPath),
      output: process.stdout,
      terminal: false,
    });

    const startTime = Date.now();
    const { size } = await fs.promises.stat(dumpPath);
    let progress = 0;

    let queryCounter = 0;
    let query = "";
    let delimiter = ";";
    for await (const line of rl) {
      progress += Buffer.byteLength(line, "utf8");

      // Ignore comment lines
      if (line.startsWith("--")) {
        continue;
      }

      // Handle delimiter command
      if (line.startsWith("DELIMITER")) {
        delimiter = line.split("DELIMITER ")[1];
        continue;
      }

      query += line;

      if (line.endsWith(delimiter)) {
        if (delimiter !== ";") {
          query = query.replace(/;\s*$/, "");
          query = query.replace(new RegExp(delimiter, "g"), ";");
        }

        try {
          await connection.query({ sql: query, timeout: 60000 });
          query = "";
          queryCounter++;

          const elapsedSeconds = Math.round((Date.now() - startTime) / 1000);
          const percentage = ((progress / size) * 100).toFixed(2);

          process.stdout.clearLine();
          process.stdout.cursorTo(0);
          process.stdout.write(
            `Elapsed time: ${formatTime(
              elapsedSeconds
            )} | Progress: ${percentage}% | Executed queries: ${queryCounter}`
          );
        } catch (err) {
          if (err.code === "PROTOCOL_SEQUENCE_TIMEOUT") {
            console.log(`\nError executing query: ${query}`);
            throw new Error(
              `Query execution timed out after 60 seconds. Your database storage might be full or the query is too complex. Error details: ${err.message}`
            );
          } else if (err.code === "ER_NET_PACKET_TOO_LARGE") {
            // Just in case the max_allowed_packet is not enough
            process.stdout.clearLine();
            process.stdout.cursorTo(0);
            console.error(
              `Skipped query due to packet size exceeding 'max_allowed_packet'.\n > Query: ${query.substr(
                0,
                100
              )}...`
            );
            query = "";
            // We continue the loop
          } else {
            console.log(`\nError executing query: ${query}`);
            throw err;
          }
        }
      }
    }

    console.log("\nDone.");
  } catch (err) {
    console.log(err);
    throw err;
  } finally {
    connection.end();
    process.exit();
  }
}

loadDBConfig().then(loadDBDump).catch(console.error);
