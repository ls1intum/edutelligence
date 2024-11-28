import {NextRequest, NextResponse} from "next/server";
import {
    ErrorResponse,
    SearchParamDateOrUndefined,
    SearchParamStringOrUndefined
} from "@lib/api-utils";
import applicationContainer from "@server/applicationContainer";

export async function GET(request: NextRequest) {
    try {
        const service = SearchParamStringOrUndefined(request.nextUrl.searchParams, "service");
        const from = SearchParamDateOrUndefined(request.nextUrl.searchParams, "from");
        const to = SearchParamDateOrUndefined(request.nextUrl.searchParams, "to");
        try {
            const metricsController = applicationContainer.getMetricsController();
            const metrics = await metricsController.GetMetricsForDashboard(service, from, to);
            return NextResponse.json(metrics, { status: 200 });
        } catch (error) {
            return ErrorResponse(error, 500);
        }
    } catch (error) {
        return ErrorResponse(error, 400);
    }
}