import { NextResponse } from "next/server";
import { ErrorResponse } from "@lib/api-utils";
import applicationContainer from "@server/applicationContainer";

export async function GET() {
  try {
    const metricsService = applicationContainer.getMetricsService();
    const services = await metricsService.getRegisteredServices();
    return NextResponse.json(services, { status: 200 });
  } catch (error) {
    return ErrorResponse(error, 500);
  }
}
