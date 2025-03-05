import { NextApiRequest, NextApiResponse } from "next";
import { DataMode } from "@/model/data_mode";
import { getProgressStatsFromFileSync } from "@/helpers/get_data";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse) {
  const { dataMode, expertEvaluationId } = req.query as {
    dataMode: DataMode;
    expertEvaluationId: string;
  };

  let progressStats = getProgressStatsFromFileSync(dataMode, expertEvaluationId);
  return res.status(200).json(progressStats)
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateDataModeMiddleware(req, res, () => handler(req, res));
}
