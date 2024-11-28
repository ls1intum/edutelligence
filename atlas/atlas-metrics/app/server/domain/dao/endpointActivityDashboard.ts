import {z} from "zod";
import {ChartDataItemDAO, ChartDataItemSchema} from "@server/domain/dao/chartDataItem";

export interface EndpointActivityDashboardDAO {
    timeSeries: ChartDataItemDAO[];
}

export const EndpointActivityDashboardSchema = z.object({
    timeSeries: ChartDataItemSchema.array(),
});