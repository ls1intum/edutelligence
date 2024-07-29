import type { NextApiRequest, NextApiResponse } from "next";
import archiver from "archiver";
import fs from "fs";
import path from "path";
import { getDataModeParts } from "@/helpers/get_data";

const EXPORT_DIR = path.join(process.cwd(), "data");

async function handler(req: NextApiRequest, res: NextApiResponse) {
  const { dataMode } = req.query as { dataMode: string };
  const directoryPath = path.join(EXPORT_DIR, ...getDataModeParts(dataMode));
  
  if (!fs.existsSync(directoryPath)) {
    return res.status(404).json({ error: "Directory not found" });
  }
  
  res.setHeader("Content-Type", "application/zip");
  res.setHeader("Content-Disposition", `attachment; filename=${dataMode}.zip`);
  
  const archive = archiver("zip", { zlib: { level: 9 } });
  archive.on("error", (err) => res.status(500).send({ error: err.message }));
  archive.pipe(res);
  
  archive.directory(directoryPath, false);
  await archive.finalize();
}

export default handler;
