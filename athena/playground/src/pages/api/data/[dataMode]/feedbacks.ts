import type { NextApiRequest, NextApiResponse } from "next";
import type { Feedback } from "@/model/feedback";
import type { DataMode } from "@/model/data_mode";

import { getFeedbacks } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Feedback[]>) {
  const { dataMode } = req.query as { dataMode: DataMode };
  const feedbacks = getFeedbacks(dataMode, undefined, getOriginFromRequest(req));
  res.status(200).json(feedbacks);
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateDataModeMiddleware(req, res, () => handler(req, res));
}
