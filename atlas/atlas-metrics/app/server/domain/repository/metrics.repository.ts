import { EndpointActivityFullDAO } from "@server/domain/dao/endpointActivity";
import { RequestType } from "@server/domain/dao/RequestTypes";

export interface IMetricsRepository {
  saveEndpointActivity(
    service: string,
    version: string,
    endpoint: string,
    type: RequestType,
    date: Date,
  ): Promise<void>;

  getEndpointActivity(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityFullDAO[]>;
}
