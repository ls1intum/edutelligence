import type { NextApiRequest, NextApiResponse } from "next";
import type { Feedback } from "@/model/feedback";
import type { Mode } from "@/model/mode";

import { getFeedbacks } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateModeMiddleware } from "@/helpers/validate_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse<Feedback[]>) {
  const { mode } = req.query as { mode: Mode };
  const feedbacks = getFeedbacks(mode, undefined, getOriginFromRequest(req));
  res.status(200).json(feedbacks);
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateModeMiddleware(req, res, () => handler(req, res));
}
