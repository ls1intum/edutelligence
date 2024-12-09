import { IMetricsRepository } from "@server/domain/repository/metrics.repository";
import { EndpointActivityBucketDAO } from "@server/domain/dao/endpointActivityBucket";
import { RequestType } from "@server/domain/dao/RequestTypes";
import { EndpointActivityFullDAO } from "@server/domain/dao/endpointActivity";

export interface IMetricsService {
  /**
   * Register endpoint activity for a service, version, endpoint, and request type.
   *
   * @param service the service for which to register endpoint activity
   * @param version the version of the service
   * @param endpoint the endpoint of the service
   * @param type the type of request
   */
  registerEndpointActivity(
    service: string,
    version: string,
    endpoint: string,
    type: RequestType,
  ): Promise<void>;

  /**
   * Get endpoint activity, optionally filtered by service, version, endpoint, type, and date range.
   *
   * @param service the service for which to fetch endpoint activity for (optional: limits the result to a specific service)
   * @param version the version of the service (optional: limits the result to a specific version)
   * @param endpoint the endpoint of the service (optional: limits the result to a specific endpoint)
   * @param type the type of request (optional: limits the result to a specific request type)
   * @param from the start date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the beginning of time)
   * @param to the end date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the end of time)
   */
  getEndpointActivity(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityFullDAO[]>;

  /**
   * Get endpoint activity by day, optionally filtered by service, version, endpoint, type, and date range.
   *
   * @param service the service for which to fetch endpoint activity for (optional: limits the result to a specific service)
   * @param version the version of the service (optional: limits the result to a specific version)
   * @param endpoint the endpoint of the service (optional: limits the result to a specific endpoint)
   * @param type the type of request (optional: limits the result to a specific request type)
   * @param from the start date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the beginning of time)
   * @param to the end date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the end of time)
   */
  getEndpointActivityByDay(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityBucketDAO[]>;

  /**
   * Get all registered services.
   */
  getRegisteredServices(): Promise<string[]>;
}

export class MetricsServiceImpl implements IMetricsService {
  private metricsRepository: IMetricsRepository;

  constructor(metricsRepository: IMetricsRepository) {
    this.metricsRepository = metricsRepository;
  }

  async registerEndpointActivity(
    service: string,
    version: string,
    endpoint: string,
    type: RequestType,
  ): Promise<void> {
    await this.metricsRepository.saveEndpointActivity(service, version, endpoint, type, new Date());
  }

  async getEndpointActivity(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityFullDAO[]> {
    return await this.metricsRepository.getEndpointActivity(
      service,
      version,
      endpoint,
      type,
      from,
      to,
    );
  }

  async getEndpointActivityByDay(
    service?: string,
    version?: string,
    endpoint?: string,
    type?: RequestType,
    from?: Date,
    to?: Date,
  ): Promise<EndpointActivityBucketDAO[]> {
    const endpointActivity = await this.metricsRepository.getEndpointActivity(
      service,
      version,
      endpoint,
      type,
      from,
      to,
    );
    const groupedData = new Map<string, { type: RequestType; date: Date; count: number }>();

    endpointActivity.forEach(({ endpoint, type, date }) => {
      const normalizedDate = new Date(date);
      normalizedDate.setHours(0, 0, 0, 0);

      const key = `${endpoint}_${type}_${normalizedDate.toISOString()}`;

      if (!groupedData.has(key)) {
        groupedData.set(key, { type: type, date: normalizedDate, count: 0 });
      }
      groupedData.get(key)!.count += 1;
    });

    return Array.from(groupedData.entries()).map(([key, { type, date, count }]) => {
      const endpoint = key.split("_")[0]; // Extract endpoint from the key
      return { endpoint, type, date, count };
    });
  }

  async getRegisteredServices(): Promise<string[]> {
    const services = await this.metricsRepository.getRegisteredServices();
    return services.sort();
  }
}
