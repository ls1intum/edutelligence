import type { NextApiRequest, NextApiResponse } from "next";
import type { DataMode } from "@/model/data_mode";

import { promises as fs } from "fs";
import path from "path";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";
import { getDataModeParts } from "@/helpers/get_data";

// Keep route segments in a shape we can safely work with.
function normalizeSegments(segments: string[]): string[] {
  const out: string[] = [];
  for (const seg of segments) {
    if (!seg) throw new Error("Bad path");
    if (seg === "." || seg === "..") throw new Error("Bad path");
    if (seg.includes("\0")) throw new Error("Bad path");
    if (seg.includes("/") || seg.includes("\\")) throw new Error("Bad path");
    out.push(seg);
  }
  return out;
}

// Build a concrete folder location from a base + segments.
function toFolderPath(baseDir: string, userSegments: string[]): string {
  const safeSegments = normalizeSegments(userSegments);
  const target = path.resolve(baseDir, ...safeSegments);

  // Ensure the final location is still tied to the base directory.
  const baseWithSep = path.resolve(baseDir) + path.sep;
  if (!target.startsWith(baseWithSep)) {
    throw new Error("Bad path");
  }

  return target;
}

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  try {
    const { dataMode, exerciseId, path: userPath } = req.query as {
      dataMode: DataMode;
      exerciseId: string;
      path: string[];
    };

    // exerciseId is expected to be a simple token.
    if (!/^[a-zA-Z0-9_-]+$/.test(exerciseId)) {
      res.status(400).json({ error: "Invalid exerciseId" });
      return;
    }

    // Root for this exercise’s data.
    const baseDir = path.resolve(
      process.cwd(),
      "data",
      ...getDataModeParts(dataMode),
      `exercise-${exerciseId}`
    );

    // Where we’ll read from.
    const folderPath = toFolderPath(baseDir, userPath ?? []);

    const stat = await fs.stat(folderPath);
    if (!stat.isDirectory()) {
      res.status(404).json({ error: "Folder not found" });
      return;
    }

    const fileMap: Record<string, string> = {};

    const walk = async (dir: string, relativePrefix = "") => {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        const relPath = relativePrefix
          ? `${relativePrefix}/${entry.name}`
          : entry.name;

        // Skip link-like entries.
        if (entry.isSymbolicLink()) continue;

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
    // Treat path issues as simple bad requests.
    if (err?.message === "Bad path") {
      res.status(400).json({ error: "Invalid path" });
      return;
    }
    if (err?.code === "ENOENT") {
      res.status(404).json({ error: "Folder not found" });
      return;
    }

    console.error("Error building filemap:", err);
    res.status(500).json({ error: "Failed to build filemap" });
  }
};

export default async function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  await new Promise<void>((resolve, reject) => {
    validateDataModeMiddleware(req, res, () => {
      Promise.resolve(handler(req, res))
        .then(resolve)
        .catch(reject);
    });
  });
}
