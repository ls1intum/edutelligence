import type { NextApiRequest } from "next/types";

export default function getOriginFromRequest(req: NextApiRequest): string {
  const host = (req.headers["x-forwarded-host"] ?? req.headers.host) ?? "localhost";

  let protocol: string | undefined;

  const forwardedProto = req.headers["x-forwarded-proto"];
  if (typeof forwardedProto === "string") {
    protocol = forwardedProto.split(",")[0];
  } else if (Array.isArray(forwardedProto)) {
    protocol = forwardedProto[0];
  }

  if (!protocol && typeof req.headers.referer === "string") {
    try {
      protocol = new URL(req.headers.referer).protocol.replace(":", "");
    } catch (error) {
      console.warn("Failed to parse referer header", error);
    }
  }

  if (!protocol) {
    // req.socket.encrypted is truthy when the request reached Next via HTTPS.
    protocol = (req.socket as { encrypted?: boolean })?.encrypted ? "https" : "http";
  }

  return `${protocol}://${host}`;
}
