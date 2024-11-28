import { NextApiRequest, NextApiResponse } from "next";
import { DataMode } from "@/model/data_mode";
import { getProgressFromFileSync, saveProgressToFileSync } from "@/helpers/get_data";
import { validateDataModeMiddleware } from "@/helpers/validate_data_mode_middleware";
import { ExpertEvaluationProgress } from "@/model/expert_evaluation_progress";

function handler(req: NextApiRequest, res: NextApiResponse) {
    if (req.method == 'PUT') {
        const { dataMode, expertEvaluationId, expertId } = req.query as {
            dataMode: DataMode;
            expertEvaluationId: string;
            expertId: string
        };
        const expertEvaluationProgress: ExpertEvaluationProgress = req.body;

        saveProgressToFileSync(dataMode, expertEvaluationId, expertId, expertEvaluationProgress);
        return res.status(200).json({ message: 'Progress saved successfully' });

    } else if (req.method == 'GET') {
        const { dataMode, expertEvaluationId, expertId } = req.query as {
            dataMode: DataMode;
            expertEvaluationId: string;
            expertId: string
        };
        let progress = getProgressFromFileSync(dataMode, expertEvaluationId, expertId);

        if (!progress || Object.keys(progress).length === 0) {
            return res.status(404).json({ message: 'Progress not found' });
        }
        return res.status(200).json(progress);

    } else {
        res.setHeader('Allow', ['POST']);
        return res.status(405).json({ message: 'Only GET or PUT requests allowed' });
    }
}

export default function handlerWithMiddleware(
    req: NextApiRequest,
    res: NextApiResponse
) {
    validateDataModeMiddleware(req, res, () => handler(req, res));
}
