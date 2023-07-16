import mysql from "mysql2/promise";
import readline from "readline";
import fs from "fs";
import inquirer from "inquirer";
import { loadDBConfig } from "./db_config.mjs";

// To display elapsed time in HH:MM:SS format
function formatTime(seconds) {
  return new Date(seconds * 1000).toISOString().substring(11, 8);
}

/**
 * Setup the database and return a connection
 * 
 * If the database already exists, the user is asked if it should be dropped and recreated.
 * 
 * @param config - The database config (host, port, user, password, database)
 * @returns {mysql.Connection} The connection to the database
 */
async function setupDatabase(config) {
  const connection = await mysql.createConnection({
    host: config.host,
    user: config.user,
    port: config.port,
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

/**
 * Load a database dump into the database
 * 
 * @param config - The database config (host, port, user, password, database)
 */
async function loadDBDump(config) {
  const connection = await setupDatabase(config);

  const { dumpPath } = await inquirer.prompt([
    {
      type: "input",
      name: "dumpPath",
      message: "Enter path to database dump:",
    },
  ]);

  // Verify that max_allowed_packet is set to at least 256MB
  //
  // This is necessary because the database dump is too large to be loaded with the default value.
  // If it is too small, the script would fail with the following error:
  // "ER_NET_PACKET_TOO_LARGE: Got a packet bigger than 'max_allowed_packet' bytes"
  //
  // This can probably be removed in the future. The text_cluster table seems to be the problem. 
  // Which we will drop later anyway.
  const [rows] = await connection.query(
    "SHOW VARIABLES LIKE 'max_allowed_packet';"
  );
  if (rows.length !== 0 && rows[0].Value !== null) {
    const currentMaxAllowedPacket = rows[0].Value;
    console.log(
      `Current max_allowed_packet is set to ${currentMaxAllowedPacket} bytes.`
    );
    if (currentMaxAllowedPacket < 268435456) {
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

  // Load the database dump
  try {
    console.log("Loading database dump this may take a while (+30-60min)...");

    // Read the dump line by line since it is too large to be read at once
    const rl = readline.createInterface({
      input: fs.createReadStream(dumpPath),
      output: process.stdout,
      terminal: false,
    });

    // Track progress
    const startTime = Date.now();
    const { size } = await fs.promises.stat(dumpPath);
    let progress = 0;

    let queryCounter = 0;
    let query = "";
    let delimiter = ";";
    for await (const line of rl) {
      progress += Buffer.byteLength(line, "utf8");

      // Ignore comment lines in the dump
      // They start with "--"
      if (line.startsWith("--")) {
        continue;
      }

      // Handle delimiter command
      // The delimiter command is used to change the delimiter from ";" to something else
      // The dump uses this so we have to handle it
      if (line.startsWith("DELIMITER")) {
        delimiter = line.split("DELIMITER ")[1];
        continue;
      }

      // Accumulate query lines
      query += line;

      // Execute the query if the query delimiter is reached
      if (line.endsWith(delimiter)) {
        // Remove the custom delimiter from the query
        // A custom delimiter is used to break the query into multiple lines
        // We have to remove it before executing the query
        if (delimiter !== ";") {
          query = query.replace(/;\s*$/, "");
          query = query.replace(new RegExp(delimiter, "g"), ";");
        }

        try {
          await connection.query({ sql: query, timeout: 60000 });
          
          // Reset query
          query = "";

          // Report progress
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
          // Handle errors that might occur during query execution
          if (err.code === "PROTOCOL_SEQUENCE_TIMEOUT") {
            // If the query times out, we abort the script
            console.log(`\nError executing query: ${query}`);
            throw new Error(
              `Query execution timed out after 60 seconds. Your database storage might be full or the query is too complex. Error details: ${err.message}`
            );
          } else if (err.code === "ER_NET_PACKET_TOO_LARGE") {
            // If the query is too large and errors, we skip it
            // Just in case the max_allowed_packet is not enough
            process.stdout.clearLine();
            process.stdout.cursorTo(0);
            console.error(
              `Skipped query due to packet size exceeding 'max_allowed_packet'.\n > Query: ${query.substring(
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
    console.error(err);
    throw err;
  } finally {
    connection.end();
    process.exit();
  }
}

loadDBConfig().then(loadDBDump).catch(console.error);
