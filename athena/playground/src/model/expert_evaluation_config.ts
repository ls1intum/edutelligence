import { Exercise } from "@/model/exercise";
import { Metric } from "@/model/metric";

export type ExpertEvaluationConfig = {
    type: "evaluation_config";
    started: boolean;
    creationDate: Date;
    id: string;
    name: string;
    metrics: Metric[];
    exercises: Exercise[];
    expertIds?: string[];
    mappings?: { [key: string]: string };
}
