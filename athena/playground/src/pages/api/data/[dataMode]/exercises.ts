import type { NextApiRequest, NextApiResponse } from "next";
import type { Exercise } from "@/model/exercise";
import type { DataMode } from "@/model/data_mode";

import { getExercises } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Exercise[]>) {
  const { dataMode } = req.query as { dataMode: DataMode };
  res.status(200).json(getExercises(dataMode, getOriginFromRequest(req)));
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateDataModeMiddleware(req, res, () => handler(req, res));
}
