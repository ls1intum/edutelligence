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
  const forwardHeaders = [
    "X-Module-Config", 
    "X-Experiment-ID", 
    "X-Module-Configuration-ID",
    "X-Run-ID",
  ]

  const headers = Object.fromEntries(
    forwardHeaders.flatMap((header) => {
      const value = req.headers[header.toLowerCase()] as string | undefined;
      return value ? [[header, value]] : [];
    })
  )
  
  if (!secret) {
    console.warn("No secret provided");
  }
  try {
    response = await fetch(url as string, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Authorization": secret,
        ...headers,
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
