import type { NextApiRequest, NextApiResponse } from "next";
import type { Submission } from "@/model/submission";
import type { DataMode } from "@/model/data_mode";

import { getSubmissions } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Submission[]>) {
  const { dataMode, exerciseId } = req.query as { dataMode: DataMode; exerciseId: string };
  const parsedExerciseId = exerciseId ? parseInt(exerciseId) : undefined;
  if (parsedExerciseId === undefined) {
    res.status(404).json([]);
    return;
  }
  try {
    const submissions = getSubmissions(
      dataMode,
      parsedExerciseId,
      getOriginFromRequest(req)
    );
    res.status(200).json(submissions);
  } catch (e) {
    console.error(e);
    res.status(404).json([]);
  }
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateDataModeMiddleware(req, res, () => handler(req, res));
}
