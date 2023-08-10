import type { NextApiRequest, NextApiResponse } from "next";

export const config = {
  api: {
      bodyParser: {
          sizeLimit: '25mb'
      }
  }
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  // needed for CORS
  // TODO: check the security implications of this
  const url = req.query.url;
  let response;
  const secret = req.headers["authorization"] as string;
  const moduleConfig = req.headers["x-module-config"] as string | undefined;
  if (!secret) {
    console.warn("No secret provided");
  }
  try {
    response = await fetch(url as string, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Authorization": secret,
        ...(moduleConfig && { "X-Module-Config": moduleConfig }),
      },
      method: req.method,
      ...(req.method === "POST" ? { body: JSON.stringify(req.body) } : {}),
    });
  } catch (error) {
    console.error("Fetch failed:", error);
    res.status(503).end();
    return;
  }
  if (!response.ok) {
    console.error("Response not ok:", response);
    res.status(response.status).json(await response.json());
    return;
  }
  res.status(200).json(await response.json());
}
