import type {NextApiRequest, NextApiResponse} from 'next';


export default async function handler(
    req: NextApiRequest,
    res: NextApiResponse<any>
) {
    // needed for CORS
    const url = req.query.url;
    let response;
    try {
        response = await fetch(url as string);
    } catch (error) {
        console.error('Fetch failed:', error);
        res.status(503);
        return;
    }
    res.status(200).json(await response.json());
}
