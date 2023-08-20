import type { NextApiRequest, NextApiResponse } from "next";

const allowedModes = ["example", "evaluation"];

export const validateDataModeMiddleware = (
  req: NextApiRequest,
  res: NextApiResponse,
  next: Function
) => {
  const { dataMode } = req.query;
  if (!allowedModes.includes(dataMode as string)) {
    return res.status(404).end();
  }
  next();
};
