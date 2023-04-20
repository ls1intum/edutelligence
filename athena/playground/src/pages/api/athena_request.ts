import type {NextApiRequest, NextApiResponse} from 'next';


export default async function handler(
    req: NextApiRequest,
    res: NextApiResponse
) {
    console.log(JSON.stringify(req.body));
    // needed for CORS
    // TODO: check the security implications of this
    const url = req.query.url;
    let response;
    try {
        response = await fetch(
            url as string,
            {
                headers: {
                    'Content-Type': 'application/json',
                },
                method: req.method,
                body: JSON.stringify(req.body)
            }
        );
    } catch (error) {
        console.error('Fetch failed:', error);
        res.status(503);
        return;
    }
    if (!response.ok) {
        console.error('Response not ok:', response);
        res.status(response.status).json(await response.json());
        return;
    }
    res.status(200).json(await response.json());
}
