import { NextApiRequest, NextApiResponse } from "next";

const allowedModes = ["example", "evaluation"];

export const validateModeMiddleware = (
  req: NextApiRequest,
  res: NextApiResponse,
  next: Function
) => {
  const { mode } = req.query;
  if (!allowedModes.includes(mode as string)) {
    return res.status(404).end();
  }
  next();
};
