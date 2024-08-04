import type { NextApiRequest, NextApiResponse } from "next";
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
  
  fs.rmSync(directoryPath, { recursive: true, force: true });
  res.status(200).json({ success: true });
}

export default handler;
