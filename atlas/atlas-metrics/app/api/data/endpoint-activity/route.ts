import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { RequestType } from "@server/domain/dao/RequestTypes";
import applicationContainer from "@server/applicationContainer";
import {
  ErrorResponse,
  SearchParamDateOrUndefined,
  SearchParamEnumOrUndefined,
  SearchParamStringOrUndefined,
} from "@lib/api-utils";

const PutEndpointActivityBodySchema = z.object({
  service: z.string(),
  version: z.string(),
  endpoint: z.string(),
  type: z.nativeEnum(RequestType),
});

export async function PUT(request: NextRequest) {
  const body = await request.json();
  const parsed = PutEndpointActivityBodySchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      { message: `Could not register endpoint activity - Invalid body - ${parsed.error}` },
      { status: 400 },
    );
  }

  const metricsService = applicationContainer.getMetricsService();
  const { service, version, endpoint, type } = parsed.data;
  await metricsService.registerEndpointActivity(service, version, endpoint, type);

  return NextResponse.json(
    { message: `Successfully registered endpoint activity` },
    { status: 200 },
  );
}

export async function GET(request: NextRequest) {
  try {
    const service = SearchParamStringOrUndefined(request.nextUrl.searchParams, "service");
    const version = SearchParamStringOrUndefined(request.nextUrl.searchParams, "version");
    const endpoint = SearchParamStringOrUndefined(request.nextUrl.searchParams, "endpoint");
    const type = SearchParamEnumOrUndefined(request.nextUrl.searchParams, "type", RequestType);
    const from = SearchParamDateOrUndefined(request.nextUrl.searchParams, "from");
    const to = SearchParamDateOrUndefined(request.nextUrl.searchParams, "to");
    try {
      const metricsService = applicationContainer.getMetricsService();
      const endpointActivity = await metricsService.getEndpointActivity(
        service,
        version,
        endpoint,
        type,
        from,
        to,
      );
      return NextResponse.json(endpointActivity, { status: 200 });
    } catch (error) {
      return ErrorResponse(error, 500);
    }
  } catch (error) {
    return ErrorResponse(error, 400);
  }
}
