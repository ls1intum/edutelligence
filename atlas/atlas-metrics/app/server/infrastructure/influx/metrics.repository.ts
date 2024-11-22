import {IMetricsRepository} from "@/app/domain/repository/metrics.repository";
import {InfluxClient, InfluxMetricsPoint} from "@/app/server/infrastructure/influx/influx";
import {Point} from "@influxdata/influxdb-client";
import {RawEndpointActivityDAO} from "@/app/domain/dao/endpointActivity";
import {validateEndpointActivitySchema} from "@/app/server/infrastructure/influx/models/endpointActivity.schema";

enum Measurement {
    ENDPOINT_ACTIVITY = "endpoint_activity",
}

export class MetricsRepositoryImpl implements IMetricsRepository {
    constructor(private readonly influxClient: InfluxClient) {}

    async saveEndpointActivity(service: string, version: string, endpoint: string, date: Date): Promise<void> {
        const point = new Point(Measurement.ENDPOINT_ACTIVITY).timestamp(date).tag("service", service).tag("version", version).stringField("endpoint", endpoint);
        this.influxClient.writePoint(point);
    }

    async getEndpointActivity(service: string, version?: string, endpoint?: string): Promise<RawEndpointActivityDAO[]> {
        const versionFilter = version ? `|> filter(fn: (r) => r.version == "${version}")` : "";
        const endpointFilter = endpoint ? `|> filter(fn: (r) => r.endpoint == "${endpoint}")` : "";
        const query = `
        from(bucket: "${this.influxClient.bucket}")
            |> range(start: 0)
            |> filter(fn: (r) => r.service == "${service}")
            ${versionFilter}
            ${endpointFilter}
            |> filter(fn: (r) => r._measurement == "${Measurement.ENDPOINT_ACTIVITY}")
        `;
        const rows = await this.influxClient.collectRows(query);
        return validateEndpointActivitySchema(rows);
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