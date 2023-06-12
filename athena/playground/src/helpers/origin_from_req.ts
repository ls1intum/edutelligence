import { NextApiRequest } from "next/types";

export default function getOriginFromRequest(req: NextApiRequest): string {
    const host = req.headers.host;
    const protocol = req.headers['x-forwarded-proto'];
    return `${protocol}://${host}`;
}