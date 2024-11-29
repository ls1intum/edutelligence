import { z } from "zod";
import {
  TimeSeriesChartDataItemDAO,
  TimeSeriesChartDataItemSchema,
  ChartDataItemDAO,
  ChartDataItemSchema,
} from "@server/domain/dao/ChartDataItem";

export interface EndpointActivityDashboardDAO {
  timeSeries: TimeSeriesChartDataItemDAO[];
  byType: ChartDataItemDAO[];
  byCategory: ChartDataItemDAO[];
}

export const EndpointActivityDashboardSchema = z.object({
  timeSeries: TimeSeriesChartDataItemSchema.array(),
  byType: ChartDataItemSchema.array(),
  byCategory: ChartDataItemSchema.array(),
});
