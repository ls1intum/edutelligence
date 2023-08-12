import inquirer from "inquirer";
import axios from "axios";
import JSZip from "jszip";
import fs from "fs";
import path from "path";

import { programming, evaluationOutputDirPath } from "./utils.mjs";

// Number of times to retry a fetch if it fails
const fetchRetries = 4;
// Delay between fetch retries in milliseconds
const fetchRetryDelay = 1000;
const timeout = 60 * 1000 * 10; // 10 minutes
// Number of repositories to download in parallel
const batchSize = 25;

// The Axios instance used for authenticated requests (after calling `setupAuthenticatedClient()`)
let artemisInstance = null;

/**
 * Setup an authenticated Axios instance for Artemis (stored globally in `artemisInstance`).
 */
async function setupAuthenticatedClient() {
  const { server } = await inquirer.prompt({
    type: "input",
    name: "server",
    message: "Enter the Artemis server:",
    default: "https://artemis.cit.tum.de",
  });

  const baseURL = `${server}/api`;
  // Validate the server URL
  if (!/^https?:\/\/.+/.test(baseURL)) {
    console.error("Invalid server URL provided.");
    process.exit(1);
  }

  const { username, password } = await inquirer.prompt([
    {
      type: "input",
      name: "username",
      message: "Enter your Artemis username:",
    },
    {
      type: "password",
      name: "password",
      message: "Enter your Artemis password:",
    },
  ]);

  const axiosInstance = axios.create({
    baseURL,
    timeout,
  });

  try {
    const response = await axiosInstance.post("/public/authenticate", {
      username,
      password,
    });

    if (response.status !== 200) {
      console.error("Failed to authenticate:", response.data.title);
      process.exit(1);
    }

    const authCookie = response.headers["set-cookie"].find((cookie) =>
      cookie.trim().startsWith("jwt=")
    );

    if (!authCookie) {
      console.error("Failed to authenticate: No cookie received.");
      process.exit(1);
    }

    // Add the authCookie to the Axios instance for authenticated requests
    axiosInstance.defaults.headers.Cookie = authCookie;

    console.log("Authenticated successfully");
    artemisInstance = axiosInstance;
  } catch (error) {
    console.error("An error occurred during authentication:");
    throw error;
  }
}

/**
 * Fetches an array buffer from the specified URL, using the globally authenticated Axios instance.
 * Automatically retries the request if it fails, up to a specified number of attempts.
 *
 * @param {string} url - The URL of the resource to fetch as an array buffer.
 * @param {object} [body] - The post body of the request (optional).
 * @param {number} [retries=fetchRetries] - The number of times to retry the request if it fails (optional, default is fetchRetries).
 * @param {number} [delay=fetchRetryDelay] - The delay in milliseconds to wait between retries (optional, default is fetchRetryDelay).
 * @returns {Promise<ArrayBuffer>} A promise that resolves to the fetched array buffer.
 * @throws Will throw an error if the request fails after all retries have been exhausted.
 */
async function fetchArrayBufferWithRetry(
  url,
  body,
  retries = fetchRetries,
  delay = fetchRetryDelay
) {
  let lastError;

  for (let i = 0; i <= retries; i++) {
    try {
      const response =
        body === undefined
          ? await artemisInstance.get(url, {
              responseType: "arraybuffer",
            })
          : await artemisInstance.post(url, body, {
              responseType: "arraybuffer",
            });

      return response.data;
    } catch (error) {
      console.warn(
        "An error occurred while fetching the array buffer. Retrying...",
        JSON.stringify(error)
      );
      lastError = error;

      // Wait for the specified delay (in milliseconds) before retrying
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  console.error(
    "Failed to fetch the array buffer after",
    retries,
    "retries:",
    JSON.stringify(lastError)
  );
  throw lastError; // Re-throw the last error after all retries have been exhausted
}

/**
 * Download all material repositories for a given exercise.
 *
 * The material repositories are downloaded to the `evaluationOutputDirPath` directory in the following structure:
 * {evaluationOutputDirPath}
 * ├── exercise-{exerciseId}
 * │   ├── template
 * │   │   ├── ...
 * │   ├── solution
 * │   │   ├── ...
 * │   ├── tests
 * │   │   ├── ...
 *
 * @param {number} exerciseId The ID of the exercise
 * @returns {Promise<boolean>} A promise that resolves to `true` if the exercise material was downloaded successfully, or `false` otherwise.
 */
async function downloadMaterial(exerciseId) {
  try {
    console.log(`MATERIAL - Start downloading exercise ${exerciseId}`);
    const url = `/programming-exercises/${exerciseId}/export-instructor-exercise`;
    const data = await fetchArrayBufferWithRetry(url);
    console.log(`MATERIAL - Finished downloading exercise ${exerciseId}`);

    const exercisePath = path.join(
      evaluationOutputDirPath,
      `exercise-${exerciseId}`
    );

    const materialData = await JSZip.loadAsync(data);

    // There is only one zip file in the material zip, which contains the exercise, solution and tests zips
    // The material zip also contains problemstatement.md and details.json but we don't need them
    const zipFile = Object.values(materialData.files).find((file) =>
      file.name.endsWith(".zip")
    );
    const zip = await zipFile.async("nodebuffer");
    const materialZipData = await JSZip.loadAsync(zip);

    const writeRepositoryZip = async (zipFile) => {
      // Should either be "exercise", "solution", or "tests"
      const kind = zipFile.name.match(/-(\w+).zip$/)[1];
      if (!["exercise", "solution", "tests"].includes(kind)) {
        console.warn(`MATERIAL - Unknown zip file ${zipFile.name} in zip`);
        return;
      }

      // Destination path for unzipping (solution, template, tests)
      const outputDir = path.join(
        exercisePath,
        kind === "exercise" ? "template" : kind
      ); // Rename `exercise` to `template`

      const data = await zipFile.async("nodebuffer");
      const repositoryData = await JSZip.loadAsync(data);
      await Promise.all(
        Object.values(repositoryData.files).map(async (file) => {
          if (!file.dir && !file.name.includes(".git/")) {
            const data = await file.async("nodebuffer");
            const filePath = path.join(outputDir, file.name);
            await fs.promises.mkdir(path.dirname(filePath), {
              recursive: true,
            });
            await fs.promises.writeFile(filePath, data);
          }
        })
      );
    };

    await Promise.all(
      Object.values(materialZipData.files).map(writeRepositoryZip)
    );
    return true;
  } catch (error) {
    console.error(
      `MATERIAL - An error occurred while downloading exercise ${exerciseId}:`,
      JSON.stringify(error)
    );
  }
  return false;
}

/**
 * Download all submission repositories for a given exercise.
 *
 * The submission repositories are downloaded to the `evaluationOutputDirPath` directory in the following structure:
 * {evaluationOutputDirPath}
 * ├── exercise-{exerciseId}
 * │   ├── submissions
 * │   │   ├── {submissionId1}
 * │   │   │   ├── ...
 * │   │   ├── {submissionId2}
 * │   │   │   ├── ...
 * │   │   ├── ...
 *
 * @param {number} exerciseId The ID of the exercise
 * @param {number[]} participationIds The IDs of the participations to download
 * @returns {Promise<boolean>} A promise that resolves to `true` if the submissions were downloaded successfully, or `false` otherwise.
 */
async function downloadSubmissions(exerciseId, participationIds) {
  const participationIdGroups = [];
  for (let i = 0; i < participationIds.length; i += batchSize) {
    participationIdGroups.push(
      participationIds.slice(
        i,
        Math.min(i + batchSize, participationIds.length)
      )
    );
  }

  const exercisePath = path.join(
    evaluationOutputDirPath,
    `exercise-${exerciseId}`
  );
  const submissionsPath = path.join(exercisePath, "submissions");

  // Keep track of index and progress
  let groupIndex = 0;
  let offset = 0;
  let downloaded = [];
  let failed = [];
  const total = participationIdGroups.length;
  for (const participationIdGroup of participationIdGroups) {
    const identifier = `exercise ${exerciseId}, submission ${offset + 1} to ${
      offset + participationIdGroup.length
    } batch (${groupIndex + 1}/${total})`;
    try {
      console.log(`SUBMISSIONS - Start downloading ${identifier}`);
      const url = `/programming-exercises/${exerciseId}/export-repos-by-participation-ids/${participationIdGroup.join(
        ","
      )}`;
      const data = await fetchArrayBufferWithRetry(url, {
        anonymizeRepository: true,
      });
      console.log(`SUBMISSIONS - Finished downloading ${identifier}`);

      // The response is a zip file containing a zip file for each submission
      const submissionsData = await JSZip.loadAsync(data);

      await Promise.all(
        Object.values(submissionsData.files).map(async (zipFile) => {
          if (zipFile.dir) {
            return;
          }

          const submissionId = zipFile.name.match(
            /-(\d+)-student-submission.git.zip$/
          )[1];
          const submissionZip = await zipFile.async("nodebuffer");

          // Destination path for unzipping the submission repository
          const outputDir = path.join(submissionsPath, submissionId);

          const submissionData = await JSZip.loadAsync(submissionZip);
          await Promise.all(
            Object.values(submissionData.files).map(async (file) => {
              if (!file.dir && !file.name.includes(".git/")) {
                const data = await file.async("nodebuffer");
                const filePath = path.join(outputDir, file.name);
                await fs.promises.mkdir(path.dirname(filePath), {
                  recursive: true,
                });
                await fs.promises.writeFile(filePath, data);
              }
            })
          );
        })
      );

      downloaded.push(...participationIdGroup);
    } catch (error) {
      console.error(
        `SUBMISSIONS - An error occurred while downloading ${identifier}:`,
        JSON.stringify(error)
      );
      failed.push(...participationIdGroup);
    } finally {
      groupIndex++;
      offset += participationIdGroup.length;
    }
  }
  console.log(
    `SUBMISSIONS - Downloaded exercises ${exerciseId}: ${downloaded.length}, (${failed.length} failed)`
  );
  await fs.promises.writeFile(
    path.join(exercisePath, `submissions-${Date.now()}.txt`),
    `${downloaded.length} downloaded:\n${downloaded.join(", ")}\n\n${
      failed.length
    } failed:\n${failed.join(", ")}`
  );
  return failed.length === 0;
}

/**
 * Download an exercise's material and submission repositories.
 *
 * @param exercise exercise object as in the json file
 * @returns {boolean} Whether the exercise was downloaded successfully
 */
async function download(exercise) {
  let success = true;
  console.log(`Downloading exercise ${exercise.id}...`);
  success = await downloadMaterial(exercise.id);
  if (success) {
      // both downloads have to be successful
      success = await downloadSubmissions(exercise.id, exercise.participations);
  }
  console.log(`Finished downloading exercise ${exercise.id}`);
  return success;
}

/**
 * Main entry point.
 */
async function main() {
  await setupAuthenticatedClient();

  const evaluationData = JSON.parse(
    await fs.promises.readFile(programming.inputDataPath, "utf8")
  );
  const exercises = [];
  const entries = Object.entries(evaluationData);
  for (let index = 0; index < entries.length; index++) {
    const [courseTitle, course] = entries[index];
    const { selectedExercises } = await inquirer.prompt({
      type: "checkbox",
      name: "selectedExercises",
      message: `${
        course.course_id
      } - ${courseTitle}: Which exercises would you like to download? (Course ${
        index + 1
      }/${entries.length})`,
      choices: course.exercises.map((exercise) => ({
        name: `${exercise.id} - ${exercise.title}`,
        value: exercise,
      })),
    });
    exercises.push(...selectedExercises);
  }

  console.log(`\nYou selected the following exercises:`);
  exercises.forEach((exercise) => {
    console.log(` - ${exercise.id} - ${exercise.title}`);
  });

  const { confirmDownload } = await inquirer.prompt({
    type: "confirm",
    name: "confirmDownload",
    default: true,
    message: `Confirm and start downloading ${exercises.length} exercises (this may take a while)?`,
  });

  if (!confirmDownload) {
    console.log("Aborting!");
    process.exit(0);
  }

  let downloaded = [];
  let failed = [];
  for (const exercise of exercises) {
    if (await download(exercise)) {
      downloaded.push(exercise.id);
    } else {
      failed.push(exercise.id);
    }
  }
  console.log(
    `Fully downloaded ${downloaded.length} exercises, ${failed.length} failed/incomplete`
  );
  console.log(`Failed exercises: ${failed.join(", ")}`);

  await fs.promises.writeFile(
    path.join(evaluationOutputDirPath, `download-${Date.now()}.txt`),
    `${downloaded.length} exercises downloaded:\n${downloaded.join(", ")}\n\n${
      failed.length
    } exercises failed:\n${failed.join(", ")}`
  );

  console.log("Done!");
}

main();
