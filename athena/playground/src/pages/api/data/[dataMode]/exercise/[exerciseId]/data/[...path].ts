import type { NextApiRequest, NextApiResponse } from "next";
import type { DataMode } from "@/model/data_mode";

import { promises as fs } from "fs";
import { join } from "path";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";
import { getDataModeParts } from "@/helpers/get_data";

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  try {
    const { dataMode, exerciseId, path } = req.query as {
      dataMode: DataMode;
      exerciseId: string;
      path: string[];
    };
    // example for path: ['submissions', '1'] or just ['solution']

    // Get the folder path
    const folderPath = join(
      process.cwd(),
      "data",
      ...getDataModeParts(dataMode),
      "exercise-" + exerciseId,
      ...path
    );

    // Check if the folder exists
    await fs.access(folderPath);

    const fileMap: Record<string, string> = {};

    // walk directory recursively and collect files as UTF-8 text
    const walk = async (dir: string, relativePrefix = "") => {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = join(dir, entry.name);
        const relPath = relativePrefix ? `${relativePrefix}/${entry.name}` : entry.name;
        if (entry.isDirectory()) {
          await walk(fullPath, relPath);
        } else if (entry.isFile()) {
          const buf = await fs.readFile(fullPath);
          fileMap[relPath] = buf.toString("utf8");
        }
      }
    };

    await walk(folderPath);

    res.setHeader("Content-Type", "application/json");
    res.status(200).json(fileMap);
  } catch (err: any) {
    if (err && err.code === "ENOENT") {
      res.status(404).json({ error: "Folder not found" });
    } else {
      console.error("Error building filemap:", err);
      res.status(500).json({ error: "Failed to build filemap" });
    }
  }
};

export default async function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  await new Promise<void>((resolve, reject) => {
    validateDataModeMiddleware(req, res, () => {
      Promise.resolve(handler(req, res))
        .then(() => resolve())
        .catch(reject);
    });
  });
}
