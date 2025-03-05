import type { NextApiRequest, NextApiResponse } from "next";
import type { HealthResponse } from "@/model/health_response";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<HealthResponse>
) {
  const url = req.query.url;
  let response;
  try {
    response = await fetch(`${url}/health`);
  } catch (error) {
    console.error("Fetch failed:", error);
    res.status(200).json({ status: "fetch-failed", modules: {} });
    return;
  }
  const data = await response.json();
  if (!data.status || !data.modules) {
    res
      .status(200)
      .json({ status: "no-assessment-module-manager-response", modules: {} });
    return;
  }
  // add name to all modules for convenience
  for (const [key, value] of Object.entries(data.modules)) {
    // @ts-ignore
    value.name = key;
  }
  res.status(200).json(data);
}
