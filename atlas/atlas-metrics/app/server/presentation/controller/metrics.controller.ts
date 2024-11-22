import {IMetricsService} from "@/app/domain/service/metrics.service";

export interface IMetricsController {

}

export class MetricsControllerImpl implements IMetricsController {
    constructor(
        private readonly metricsService: IMetricsService,
    ) {}
}