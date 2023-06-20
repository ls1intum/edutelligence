import type { NextApiRequest, NextApiResponse } from "next";
import type { Submission } from "@/model/submission";
import { getSubmissions } from "@/helpers/get_data";
import getOriginFromRequest from "@/helpers/origin_from_req";
import { validateModeMiddleware } from "@/helpers/validate_mode_middleware";
import { Mode } from "@/model/mode";

function handler(req: NextApiRequest, res: NextApiResponse<Submission[]>) {
  const { mode } = req.query as { mode: Mode };
  const submissions = getSubmissions(
    mode,
    undefined,
    getOriginFromRequest(req)
  );
  res.status(200).json(submissions);
}

export default function handlerWithMiddleware(
  req: NextApiRequest,
  res: NextApiResponse
) {
  validateModeMiddleware(req, res, () => handler(req, res));
}
