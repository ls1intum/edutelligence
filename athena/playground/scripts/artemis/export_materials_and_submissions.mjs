import axios from "axios";
import inquirer from "inquirer";
import JSZip from "jszip";
import fs from "fs";
import path from "path";

import {
  programming,
  findExerciseIds,
  evaluationOutputDirPath,
} from "./utils.mjs";

const axiosInstance = axios.create();

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

  const response = await axiosInstance.post("/public/authenticate", {
    username,
    password,
  });

  if (response.status === 200) {
    const jwt = response.headers["set-cookie"][0].split(";")[0].split("=")[1];
    axiosInstance.defaults.headers.common["Cookie"] = `jwt=${jwt}`;
  } else {
    console.error("Failed to authenticate");
    process.exit(1);
  }
};

const downloadMaterial = async (exerciseId) => {
  const response = await axiosInstance.get(
    `/programming-exercises/${exerciseId}/export-instructor-exercise`,
    { responseType: "arraybuffer" }
  );

  if (response.status === 200) {
    console.log(`Downloading exercise ${exerciseId}'s material`);
    const materialZip = new JSZip();
    const materialData = await materialZip.loadAsync(response.data);
    const exercisePath = path.join(
      evaluationOutputDirPath,
      `exercise-${exerciseId}`
    );

    const files = Object.keys(materialData.files);
    const zipFile = files.find((file) => file.endsWith(".zip"));

    const zip = await materialData.files[zipFile].async("nodebuffer");
    const materialZipData = await JSZip.loadAsync(zip);
    const materialZipFiles = Object.keys(materialZipData.files);

    const writeZip = async (kind) => {
      const zipFile = materialZipFiles.find((file) =>
        file.endsWith(`-${kind}.zip`)
      );
      if (zipFile) {
        const zip = await materialZipData.files[zipFile].async("nodebuffer");
        const unzipPath = path.join(
          exercisePath,
          kind === "exercise" ? "template" : kind
        );

        const zipData = await JSZip.loadAsync(zip);
        const zipFiles = Object.keys(zipData.files);
        await Promise.all(
          zipFiles.map(async (file) => {
            if (!zipData.files[file].dir) {
              const data = await zipData.files[file].async("nodebuffer");
              const filePath = path.join(unzipPath, file);
              await fs.promises.mkdir(path.dirname(filePath), {
                recursive: true,
              });
              await fs.promises.writeFile(filePath, data);
            }
          })
        );
      }
    };

    await Promise.all(["exercise", "solution", "tests"].map(writeZip));
  } else {
    console.error(`Error downloading exercise ${exerciseId}'s material`);
    process.exit(1);
  }
};

const downloadSubmissions = async (exerciseId) => {
  const response = await axiosInstance.post(
    `/programming-exercises/${exerciseId}/export-repos-by-participant-identifiers/0`,
    {
      excludePracticeSubmissions: true,
      exportAllParticipants: true,
      anonymizeStudentCommits: true,
      hideStudentNameInZippedFolder: true,
    },
    { responseType: "arraybuffer" }
  );

  if (response.status === 200) {
    console.log(`Downloaded exercise ${exerciseId}'s submissions`);
    const submissionsZip = new JSZip();
    const submissionsData = await submissionsZip.loadAsync(response.data);
    const submissionsPath = path.join(
      evaluationOutputDirPath,
      `exercise-${exerciseId}`,
      "submissions"
    );

    const submissionZipFiles = Object.keys(submissionsData.files);
    await Promise.all(
      submissionZipFiles.map(async (file) => {
        if (!submissionsData.files[file].dir) {
          const submissionId = file.match(
            /-(\d+)-student-submission.git.zip$/
          )[1];
          const zip = await submissionsData.files[file].async("nodebuffer");
          const unzipPath = path.join(submissionsPath, submissionId);

          const zipData = await JSZip.loadAsync(zip);
          const zipFiles = Object.keys(zipData.files);
          await Promise.all(
            zipFiles.map(async (file) => {
              if (!zipData.files[file].dir) {
                const data = await zipData.files[file].async("nodebuffer");
                const filePath = path.join(unzipPath, file);
                await fs.promises.mkdir(path.dirname(filePath), {
                  recursive: true,
                });
                await fs.promises.writeFile(filePath, data);
              }
            })
          );
        }
      })
    );
  } else {
    console.error(`Error downloading exercise ${exerciseId}'s submissions`);
    process.exit(1);
  }
};

const download = async (exerciseId) => {
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
};

const main = async () => {
  const { server } = await inquirer.prompt({
    type: "input",
    name: "server",
    message: "Enter the Artemis server:",
    default: "https://artemis.ase.in.tum.de",
  });
  axiosInstance.defaults.baseURL = `${server}/api`;

  await auth();

  const exerciseIds = findExerciseIds(
    JSON.parse(await fs.promises.readFile(programming.inputDataPath, "utf8"))
  );

  console.log(
    `Found the following exercise IDs in ${programming.inputDataPath}:`,
    exerciseIds
  );

  const { shouldDownloadAll } = await inquirer.prompt({
    type: "confirm",
    name: "shouldDownloadAll",
    message: "Download all exercises?",
  });

  try {
    if (shouldDownloadAll) {
      const results = await Promise.all(
        exerciseIds.map(async (exerciseId) => {
          return await download(exerciseId);
        })
      );
      const failed = results.filter((result) => !result);
      console.log(`Downloaded ${exerciseIds.length - failed.length} exercises, ${failed.length} failed`);
    } else {
      const { exerciseId } = await inquirer.prompt({
        type: "input",
        name: "exerciseId",
        message: "Enter the exercise ID to download:",
      });
      if (!await download(exerciseId)) {
        console.log("No exercise was downloaded");
      }
    }
  } catch (e) {
    console.error(`Error downloading exercise ${e.message}`);
  }

  console.log("Done!");
};

main();
