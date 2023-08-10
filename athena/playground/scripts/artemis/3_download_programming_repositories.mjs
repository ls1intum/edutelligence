import inquirer from "inquirer";
import JSZip from "jszip";
import fs from "fs";
import path from "path";

import {
  programming,
  evaluationOutputDirPath,
} from "./utils.mjs";

let baseURL = "";
let authCookie = "";

// Number of times to retry a fetch if it fails
const fetchRetryCount = 3;
// Delay between fetch retries in milliseconds
const fetchRetryDelay = 1000;
const exponentialBackoffFactor = 5; // 1, 5, 25 (seconds)
const concurrentDownloads = 5;

/**
 * Fetch a URL, retrying the fetch a specified number of times if it fails.
 *
 * @param {string} url The URL to fetch
 * @param {object} options Options to pass to fetch
 * @param {number} retryCount The number of times to retry the fetch if it fails
 * @param {number} retryDelay The delay between retries in milliseconds
 * @returns {Promise<Response>} The fetch response
 * @throws {Error} If the fetch fails after all retries
 */
async function fetchWithRetry(
  url,
  options,
  retryCount = fetchRetryCount,
  retryDelay = fetchRetryDelay
) {
  for (let i = 0; i <= retryCount; i++) {
    try {
      const response = await fetch(url, options);
      if (response.ok) {
        return response;
      }
      throw new Error(
        `HTTP ${response.status} for ${url}: ${
          response.statusText
        }\n${await response.text()}`
      );
    } catch (error) {
      if (i < retryCount) {
        const delay = retryDelay * Math.pow(exponentialBackoffFactor, i);
        console.log(
          `Fetch failed for ${url}, retrying in ${delay}ms... (${
            i + 1
          }/${retryCount + 1})`
        );
        await new Promise((resolve) => setTimeout(resolve, delay));
      } else {
        throw error;
      }
    }
  }
}

/**
 * Authenticate with Artemis
 */
async function auth() {
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

  const response = await fetch(`${baseURL}/public/authenticate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    console.error(`Failed to authenticate: ${error.title}`);
    process.exit(1);
  }

  const setCookie = response.headers.get("Set-Cookie");
  if (setCookie) {
    const cookieArray = setCookie.split(";");
    authCookie = cookieArray.find((cookie) => cookie.trim().startsWith("jwt="));
  }
  if (authCookie) {
    console.log("Authenticated successfully");
  } else {
    console.error("Failed to authenticate: No cookie received");
    process.exit(1);
  }
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
 */
async function downloadMaterial(exerciseId) {
  const response = await fetchWithRetry(
    `${baseURL}/programming-exercises/${exerciseId}/export-instructor-exercise`,
    {
      method: "GET",
      headers: {
        Cookie: authCookie,
      },
    }
  );

  if (!response.ok) {
    console.error(`Error downloading exercise ${exerciseId}'s material`);
    process.exit(1);
  }

  console.log(`Downloading exercise ${exerciseId}'s material`);
  const exercisePath = path.join(
    evaluationOutputDirPath,
    `exercise-${exerciseId}`
  );
  const data = await response.arrayBuffer();
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
      console.warn(`Unknown zip file ${zipFile.name} in material zip`);
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
          await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
          await fs.promises.writeFile(filePath, data);
        }
      })
    );
  };

  await Promise.all(
    Object.values(materialZipData.files).map(writeRepositoryZip)
  );
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
 */
async function downloadSubmissions(exerciseId) {
  const response = await fetchWithRetry(
    `${baseURL}/programming-exercises/${exerciseId}/export-repos-by-participant-identifiers/0`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: authCookie,
      },
      body: JSON.stringify({
        excludePracticeSubmissions: true,
        exportAllParticipants: true,
        anonymizeRepository: true,
      }),
    }
  );

  if (!response.ok) {
    console.error(`Error downloading exercise ${exerciseId}'s submissions`);
    process.exit(1);
  }

  console.log(`Downloaded exercise ${exerciseId}'s submissions`);
  const submissionsPath = path.join(
    evaluationOutputDirPath,
    `exercise-${exerciseId}`,
    "submissions"
  );

  // The response is a zip file containing a zip file for each submission
  const data = await response.arrayBuffer();
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
}

/**
 * Download an exercise's material and submission repositories.
 *
 * @param {number} exerciseId The ID of the exercise
 * @returns {boolean} Whether the exercise was downloaded successfully
 */
async function download(exerciseId) {
  try {
    await downloadMaterial(exerciseId);
    await downloadSubmissions(exerciseId);
    return true;
  } catch (e) {
    console.error(`Error downloading exercise ${exerciseId}`);
    console.error(` > ${e.message}`);
    console.error(
      " > Either the exercise does not exist or you do not have access to it, skipping"
    );
    return false;
  }
}

/**
 * Helper function to create a promise that resolves after a task is done.
 */
const taskPromise = (idx, task = null) =>
  new Promise((resolve) => {
    if (!task) {
      resolve(idx);
    }
    task
      .then(() => {
        resolve(idx);
      })
      .catch(() => {
        resolve(idx);
      });
  });

/**
 * Main entry point.
 */
async function main() {
  const { server } = await inquirer.prompt({
    type: "input",
    name: "server",
    message: "Enter the Artemis server:",
    default: "https://artemis.cit.tum.de",
  });

  baseURL = `${server}/api`;

  await auth();

  const evaluationData = JSON.parse(await fs.promises.readFile(programming.inputDataPath, "utf8"))
  const exercises = [];
  const entries = Object.entries(evaluationData);
  for (let index = 0; index < entries.length; index++) {
    const [courseTitle, course] = entries[index];
    const { selectedExercises } = await inquirer.prompt({
      type: 'checkbox',
      name: 'selectedExercises',
      message: `${course.course_id} - ${courseTitle}: Which exercises would you like to download? (Course ${index + 1}/${entries.length})`,
      choices: course.exercises.map(exercise => ({
        name: `${exercise.id} - ${exercise.title}`,
        value: exercise
      }))
    });
    exercises.push(...selectedExercises);
  }

  console.log(`\nYou selected the following exercises:`);
  exercises.forEach(exercise => {
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

  const exerciseIds = exercises.map((exercise) => exercise.id);

  // Only download limited exercises at a time
  const downloadPromises = Array.from({ length: concurrentDownloads }, () =>
    Promise.resolve()
  );
  const resultPromises = [];

  for (const exerciseId of exerciseIds) {
    const idx = await Promise.race(downloadPromises);
    const downloadPromise = download(exerciseId);
    resultPromises.push(downloadPromise);
    downloadPromises[idx] = taskPromise(idx, downloadPromise);
  }

  const results = await Promise.all(resultPromises);
  const failed = results.filter((result) => !result);
  console.log(
    `Downloaded ${exerciseIds.length - failed.length} exercises, ${
      failed.length
    } failed`
  );
  console.log("Done!");
}

main();
