import type { NextApiRequest, NextApiResponse } from "next";

const allowedModesRegex = /(example|evaluation(-[a-zA-Z0-9_-]+)?)/;

export const validateDataModeMiddleware = (
  req: NextApiRequest,
  res: NextApiResponse,
  next: Function
) => {
  const { dataMode } = req.query;
  if (typeof dataMode !== "string") {
    return res.status(404).end();
  }
  if (!allowedModesRegex.test(dataMode)) {
    return res.status(404).end();
  }  
  return next();
};
