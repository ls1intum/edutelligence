import { IMetricsService } from "@server/domain/service/metrics.service";
import {DashboardDataDAO} from "@server/domain/dao/dashboardData";
import {EndpointActivityBucketDAO} from "@server/domain/dao/endpointActivityBucket";
import {TimeSeriesChartDataItemDAO, ChartDataItemDAO} from "@server/domain/dao/ChartDataItem";
import {mapRequestTypeToCategory} from "@server/domain/dao/RequestTypes";

export interface IMetricsController {

  /**
   * Get metrics for the dashboard.
   *
   * @param service the service for which to fetch metrics for (optional: limits the result to a specific service)
   * @param from the start date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the beginning of time)
   * @param to the end date of the date range (optional: limits the result to a specific date range, if not provided, defaults to the end of time)
   */
  GetMetricsForDashboard(service?: string, from?: Date, to?: Date): Promise<DashboardDataDAO>;
}

export class MetricsControllerImpl implements IMetricsController {
  constructor(private readonly metricsService: IMetricsService) {}

  async GetMetricsForDashboard(service?: string, from?: Date, to?: Date) : Promise<DashboardDataDAO> {

    const endpointActivityByDay = await this.metricsService.getEndpointActivityByDay(service, undefined, undefined, undefined, from, to);

    const timeSeries = this.transformEndpointActivityToChartData(endpointActivityByDay);
    const byType = this.transformEndpointActivityToTypeChartData(endpointActivityByDay);
    const byCategory = this.transformEndpointActivityToCategoryChartData(endpointActivityByDay);

    return {
      endpointActivity: {
        timeSeries: timeSeries,
        byType: byType,
        byCategory: byCategory,
      },
    };
  }

  private transformEndpointActivityToChartData(buckets: EndpointActivityBucketDAO[]): TimeSeriesChartDataItemDAO[] {
    const groupedByDate = new Map<string, TimeSeriesChartDataItemDAO>();

    buckets.forEach(({ endpoint, date, count }) => {
      const dateString = date.toISOString().split("T")[0];

      if (!groupedByDate.has(dateString)) {
        groupedByDate.set(dateString, { date: dateString });
      }

      const dataForDate = groupedByDate.get(dateString)!;
      if (typeof dataForDate[endpoint] === "number") {
        dataForDate[endpoint] = dataForDate[endpoint] + count;
      } else {
        dataForDate[endpoint] = count;
      }
    });

    return Array.from(groupedByDate.values());
  }

  private transformEndpointActivityToTypeChartData(buckets: EndpointActivityBucketDAO[]): ChartDataItemDAO[] {
    const groupedByType = new Map<string, number>();

    buckets.forEach(({ type, count }) => {
      if (!groupedByType.has(type)) {
        groupedByType.set(type, 0);
      }

      const currentCount = groupedByType.get(type)!;
      groupedByType.set(type, currentCount + count);
    });

    return Array.from(groupedByType.entries()).map(([label, value]) => ({ label, value }));
  }

  private transformEndpointActivityToCategoryChartData(buckets: EndpointActivityBucketDAO[]): ChartDataItemDAO[] {
    const groupedByCategory = new Map<string, number>();

    buckets.forEach(({ type, count }) => {
      const category = mapRequestTypeToCategory(type);

      if (!groupedByCategory.has(category)) {
        groupedByCategory.set(category, 0);
      }

      const currentCount = groupedByCategory.get(category)!;
      groupedByCategory.set(category, currentCount + count);
    });

    return Array.from(groupedByCategory.entries()).map(([label, value]) => ({ label, value }));
  }
}
