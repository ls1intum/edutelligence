import { IMetricsService } from "@server/domain/service/metrics.service";
import {DashboardDataDAO} from "@server/domain/dao/dashboardData";
import {EndpointActivityBucketDAO} from "@server/domain/dao/endpointActivityBucket";
import {ChartDataItemDAO} from "@server/domain/dao/chartDataItem";

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

    const endpointActivityByDayForChart = this.transformEndpointActivityToChartData(endpointActivityByDay);

    return {
      endpointActivity: {
        timeSeries: endpointActivityByDayForChart,
      },
    };
  }

  private transformEndpointActivityToChartData(buckets: EndpointActivityBucketDAO[]): ChartDataItemDAO[] {
    // Create a Map to group data by date
    const groupedByDate = new Map<string, ChartDataItemDAO>();

    buckets.forEach(({ endpoint, date, count }) => {
      // Normalize date to string format (e.g., "YYYY-MM-DD")
      const dateString = date.toISOString().split("T")[0];

      if (!groupedByDate.has(dateString)) {
        groupedByDate.set(dateString, { date: dateString });
      }

      // Update the count for the endpoint on this date
      const dataForDate = groupedByDate.get(dateString)!;
      if (typeof dataForDate[endpoint] === "number") {
        dataForDate[endpoint] = dataForDate[endpoint] + count;
      } else {
        dataForDate[endpoint] = count;
      }
    });

    // Convert the grouped data to an array
    return Array.from(groupedByDate.values());
  }
}
