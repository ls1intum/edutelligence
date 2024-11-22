"use cache";

import {IMetricsService, MetricsServiceImpl} from "@/app/domain/service/metrics.service";
import {IMetricsController, MetricsControllerImpl} from "@/app/server/presentation/controller/metrics.controller";
import {InfluxClient} from "@/app/server/infrastructure/influx/influx";
import {IMetricsRepository} from "@/app/domain/repository/metrics.repository";
import {MetricsRepositoryImpl} from "@/app/server/infrastructure/influx/metrics.repository";

interface ApplicationContainer {
    getMetricsService: () => IMetricsService;
    getMetricsController: () => IMetricsController;
}

// Infrastructure Factory Functions
const createInfluxClient = (): InfluxClient => {
    const url = process.env.INFLUXDB_URL || "";
    const token = process.env.INFLUXDB_TOKEN || "";
    const org = process.env.INFLUXDB_ORG || "";
    const bucket = process.env.INFLUXDB_BUCKET || "";
    return new InfluxClient(url, token, org, bucket);
};

// Repository Factory Functions
const createMetricsRepository = (): IMetricsRepository => {
    const influxClient = createInfluxClient();
    return new MetricsRepositoryImpl(influxClient);
};

// Service Factory Functions
const createMetricsService = (): IMetricsService => {
    const metricsRepository = createMetricsRepository();
    return new MetricsServiceImpl(metricsRepository);
};

const metricsController = (): IMetricsController => {
    const metricsService = createMetricsService();
    return new MetricsControllerImpl(metricsService);
};

// Application Container with Factory Functions
const applicationContainer: ApplicationContainer = {
    getMetricsService: () => createMetricsService(),
    getMetricsController: () => metricsController(),
};

// Export the container
export default applicationContainer;