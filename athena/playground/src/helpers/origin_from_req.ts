import type { NextApiRequest } from "next/types";

export default function getOriginFromRequest(req: NextApiRequest): string {
  const host = req.headers.host;
  let protocol: string | undefined;  
  const forwardedProto = req.headers["x-forwarded-proto"];
  if (typeof forwardedProto === 'string') {
    protocol = forwardedProto.split(',')[0];
  } else if (Array.isArray(forwardedProto)) {
    protocol = forwardedProto[0];
  } else {
    protocol = 'http';
  }
  return `${protocol}://${host}`;
}
