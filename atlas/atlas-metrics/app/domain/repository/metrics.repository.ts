import { EndpointActivityFullDAO } from "@/app/domain/dao/endpointActivity";
import { RequestType } from "@/app/domain/dao/RequestTypes";

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
