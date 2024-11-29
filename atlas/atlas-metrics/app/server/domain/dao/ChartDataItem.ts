import { z } from "zod";

export interface ChartDataItemDAO {
  label: string;
  value: number;
}

export const ChartDataItemSchema = z.object({
  label: z.string(),
  value: z.number(),
});

export interface TimeSeriesChartDataItemDAO {
  date: string;
  [key: string]: number | string;
}

export const TimeSeriesChartDataItemSchema = z
  .object({
    date: z.string(),
  })
  .catchall(z.union([z.number(), z.string()]));
