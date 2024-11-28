"use cache";

import {IMetricsController, MetricsControllerImpl} from "@server/presentation/controller/metrics.controller";
import {IMetricsService, MetricsServiceImpl} from "@server/domain/service/metrics.service";
import {InfluxClient} from "@server/infrastructure/influx/influx";
import {IMetricsRepository} from "@server/domain/repository/metrics.repository";
import {MetricsRepositoryImpl} from "@server/infrastructure/influx/metrics.repository";

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
