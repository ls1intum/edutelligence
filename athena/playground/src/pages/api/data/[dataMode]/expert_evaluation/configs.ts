import { NextApiRequest, NextApiResponse } from "next";
import { DataMode } from "@/model/data_mode";
import { getAllConfigsFromFilesSync } from "@/helpers/get_data";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";

function handler(req: NextApiRequest, res: NextApiResponse) {
    if (req.method == 'GET') {
        const { dataMode, expertEvaluationId } = req.query as { dataMode: DataMode; expertEvaluationId: string };

        let configs = getAllConfigsFromFilesSync(dataMode);
        return res.status(200).json(configs);

    } else {
        return res.status(405).json({ message: 'Only GET allowed' });
    }
}

export default function handlerWithMiddleware(
    req: NextApiRequest,
    res: NextApiResponse
) {
    validateDataModeMiddleware(req, res, () => handler(req, res));
}
