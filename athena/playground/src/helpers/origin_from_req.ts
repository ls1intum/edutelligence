import type { NextApiRequest } from "next/types";

export default function getOriginFromRequest(req: NextApiRequest): string {
  let host = req.headers.host;
  let protocol: string | undefined;

  const forwardedProto = req.headers["x-forwarded-proto"];
  if (typeof forwardedProto === 'string') {
    protocol = forwardedProto.split(',')[0];
  } else if (Array.isArray(forwardedProto)) {
    protocol = forwardedProto[0];
  }

  const referer = (req.headers.referer ?? req.headers.origin) as string | undefined;
  if (!host && referer) {
    try {
      host = new URL(referer).host;
    } catch (error) {
      console.warn('Failed to parse referer host', referer, error);
    }
  }

  if (!protocol && referer) {
    try {
      protocol = new URL(referer).protocol.replace(':', '');
    } catch (error) {
      console.warn('Failed to parse referer protocol', referer, error);
    }
  }

  if (!protocol) {
    protocol = (req.socket as any)?.encrypted ? 'https' : 'http';
  }

  if (!host) {
    host = 'localhost';
  }

  return `${protocol}://${host}`;
}
