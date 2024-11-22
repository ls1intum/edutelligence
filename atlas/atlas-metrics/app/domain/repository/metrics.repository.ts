import {RawEndpointActivityDAO} from "@/app/domain/dao/endpointActivity";

export interface IMetricsRepository {
    saveEndpointActivity(service: string, version: string, endpoint: string, date: Date): Promise<void>;

    getEndpointActivity(service: string, version?: string, endpoint?: string): Promise<RawEndpointActivityDAO[]>;
}