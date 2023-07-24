import type { NextApiRequest, NextApiResponse } from "next";
import type { Submission } from "@/model/submission";
import type { Mode } from "@/model/mode";

import { getSubmissions } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateModeMiddleware } from "@/helpers/validate_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Submission[]>) {
  const { mode, exerciseId } = req.query as { mode: Mode; exerciseId: string };
  const parsedExerciseId = exerciseId ? parseInt(exerciseId) : undefined;
  if (parsedExerciseId === undefined) {
    res.status(404).json([]);
    return;
  }
  try {
    const submissions = getSubmissions(
      mode,
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
  validateModeMiddleware(req, res, () => handler(req, res));
}
