import { NextRequest, NextResponse } from "next/server";
import applicationContainer from "@server/applicationContainer";

export async function GET(request: NextRequest) {
  const moduleName = request.nextUrl.searchParams.get("module");
  if (!moduleName) {
    return NextResponse.json({ error: "Missing module query parameter" }, { status: 400 });
  }

  const metricsController = applicationContainer.getMetricsController();
  try {
    // const metrics = await metricsController.GetLatestExternalModuleUsageMetrics(moduleName);
    // return NextResponse.json(metrics);
    return NextResponse.json(null);
  } catch (error) {
    return NextResponse.json({ error }, { status: 500 });
  }
}
