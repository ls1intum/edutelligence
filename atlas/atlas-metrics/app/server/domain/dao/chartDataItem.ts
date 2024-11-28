import {z} from "zod";

export interface ChartDataItemDAO {
  date: string;
  [key: string]: number | string;
}

export const ChartDataItemSchema = z.object({
  date: z.string(), // Required date field as a string
}).catchall(z.union([z.number(), z.string()])); // Additional fields can be number or string