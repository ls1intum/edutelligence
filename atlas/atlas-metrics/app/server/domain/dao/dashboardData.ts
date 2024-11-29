import {
  EndpointActivityDashboardDAO,
  EndpointActivityDashboardSchema,
} from "@server/domain/dao/endpointActivityDashboard";
import { z } from "zod";

export interface DashboardDataDAO {
  endpointActivity: EndpointActivityDashboardDAO;
}

export const DashboardDataSchema = z.object({
  endpointActivity: EndpointActivityDashboardSchema,
});
