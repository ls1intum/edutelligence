import { InfluxClient, InfluxMetricsPoint } from "@server/infrastructure/influx/influx";
import { Point } from "@influxdata/influxdb-client";
import { validateEndpointActivitySchema } from "@server/infrastructure/influx/models/endpointActivity.schema";
import { RequestType } from "@server/domain/dao/RequestTypes";
import { IMetricsRepository } from "@server/domain/repository/metrics.repository";
import { EndpointActivityFullDAO } from "@server/domain/dao/endpointActivity";
import { validateServiceSchema } from "@server/infrastructure/influx/models/service.schema";

enum Measurement {
  ENDPOINT_ACTIVITY = "endpoint_activity",
}

const TimeRange = (from?: Date, to?: Date) => {
  if (from && to) {
    return `|> range(start: ${from.toISOString()}, stop: ${to.toISOString()})`;
  } else if (from) {
    return `|> range(start: ${from.toISOString()})`;
  } else if (to) {
    return `|> range(stop: ${to.toISOString()})`;
  } else {
    return "|> range(start: 0)";
  }
};
const ServiceFilter = (service?: string) =>
  service ? `|> filter(fn: (r) => r.service == "${service}")` : "";
const VersionFilter = (version?: string) =>
  version ? `|> filter(fn: (r) => r.version == "${version}")` : "";
const EndpointFilter = (endpoint?: string) =>
  endpoint ? `|> filter(fn: (r) => r.endpoint == "${endpoint}")` : "";
const RequestTypeFilter = (type?: RequestType) =>
  type ? `|> filter(fn: (r) => r.type == "${type}")` : "";
const MeasurementFilter = (measurement: Measurement) =>
  `|> filter(fn: (r) => r._measurement == "${measurement}")`;
const Pivot = `|> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")`;

export class MetricsRepositoryImpl implements IMetricsRepository {
  constructor(private readonly influxClient: InfluxClient) {}

  async saveEndpointActivity(
    service: string,
    version: string,
    endpoint: string,
    type: RequestType,
    date: Date,
  ): Promise<void> {
    const point = new Point(Measurement.ENDPOINT_ACTIVITY)
      .timestamp(date)
      .tag("service", service)
      .tag("version", version)
      .stringField("endpoint", endpoint)
      .stringField("type", type);
    this.influxClient.writePoint(point);
  }

  async getEndpointActivity(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityFullDAO[]> {
    const query = `
        from(bucket: "${this.influxClient.bucket}")
            ${TimeRange(from, to)}
            ${ServiceFilter(service)}
            ${VersionFilter(version)}
            ${EndpointFilter(endpoint)}
            ${RequestTypeFilter(type)}
            ${MeasurementFilter(Measurement.ENDPOINT_ACTIVITY)}
            ${Pivot}
        `;
    const rows = await this.influxClient.collectRows(query);
    return validateEndpointActivitySchema(rows);
  }

  async getRegisteredServices(): Promise<string[]> {
    const query = `
        from(bucket: "atlas-metrics")
          |> range(start: 0)
          |> filter(fn: (r) => exists r["service"])
          |> keep(columns: ["service"])
          |> distinct(column: "service")
          |> drop(columns: ["service"])
          |> rename(columns: {_value: "service"})
      `;
    const rows = await this.influxClient.collectRows(query);
    return validateServiceSchema(rows);
  }

  private writePointsToInflux = async (
    points: InfluxMetricsPoint[],
    date: Date,
    service: string,
    version: string,
  ) => {
    const result: Point[] = [];
    for (const { measurement, tags, fields } of points) {
      const point = new Point(measurement).timestamp(date);

      if (tags !== undefined) {
        for (const [key, value] of Object.entries(tags)) {
          point.tag(key, `${value}`);
        }
      }

      for (const [key, value] of Object.entries(fields)) {
        if (typeof value === "number") {
          point.intField(key, value);
        } else if (typeof value === "boolean") {
          point.booleanField(key, value);
        } else {
          point.stringField(key, value);
        }
      }

      point.tag("service", service);
      point.tag("version", version);

      result.push(point);
    }

    this.influxClient.writePoints(result);
    await this.influxClient.close();
  };
}
