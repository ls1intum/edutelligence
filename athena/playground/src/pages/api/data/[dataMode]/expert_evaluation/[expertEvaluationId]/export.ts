import type { NextApiRequest, NextApiResponse } from "next";
import path from "path";
import { exportHandler } from "@/pages/api/data/[dataMode]/data/export";

const EXPORT_DIR = path.join(process.cwd(), "data", "expert_evaluation");

async function handler(req: NextApiRequest, res: NextApiResponse) {
  const { expertEvaluationId } = req.query as { expertEvaluationId: string };
  const directoryPath = path.join(EXPORT_DIR, `evaluation_${expertEvaluationId}`);
  const filename = `evaluation_${expertEvaluationId}.zip`;

  await exportHandler(res, directoryPath, filename);
}

export default handler;
