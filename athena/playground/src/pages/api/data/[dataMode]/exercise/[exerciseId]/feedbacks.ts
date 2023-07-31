import type { NextApiRequest, NextApiResponse } from "next";
import type { Feedback } from "@/model/feedback";
import type { DataMode } from "@/model/data_mode";

import { getFeedbacks } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Feedback[]>) {
  const { dataMode, exerciseId } = req.query as { dataMode: DataMode; exerciseId: string };
  const parsedExerciseId = exerciseId ? parseInt(exerciseId) : undefined;
  if (parsedExerciseId === undefined) {
    res.status(404).json([]);
    return;
  }
  try {
    const feedbacks = getFeedbacks(
      dataMode,
      parsedExerciseId,
      getOriginFromRequest(req)
    );
    res.status(200).json(feedbacks);
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
