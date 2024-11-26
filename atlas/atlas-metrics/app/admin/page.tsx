import {Menu} from "@/components/custom/menu";
import {DataTable} from "@/components/custom/data-table";
import {EndpointActivityDAO} from "@/app/domain/dao/endpointActivity";
import {endpointActivityColumns} from "@/app/admin/columns";
import {RequestType} from "@/app/domain/dao/RequestTypes";

async function getEndpointActivityData(): Promise<EndpointActivityDAO[]> {
    // TODO: Fetch data from your API here.
    return [
        {
            date: new Date("2024-04-01T15:00:00Z"),
            endpoint: "/api/v1/endpoint8",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-02T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-03T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-04T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-05T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-06T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-07T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-08T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-09T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-10T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-11T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-12T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-13T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-14T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-15T15:00:00Z"),
            endpoint: "/api/v1/endpoint4",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-16T15:00:00Z"),
            endpoint: "/api/v1/endpoint3",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-17T15:00:00Z"),
            endpoint: "/api/v1/endpoint2",
            type: RequestType.GET
        },
        {
            date: new Date("2024-04-18T15:00:00Z"),
            endpoint: "/api/v1/endpoint1",
            type: RequestType.GET
        },
    ]
}

export default async function Admin() {
    const data = await getEndpointActivityData()
    return (
        <div className="m-5 text-center">
            <h1 className="m-10 scroll-m-20 text-4xl font-extrabold tracking-tight lg:text-5xl">
                Atlas Metrics
            </h1>
            <div className="pb-5">
                <Menu/>
            </div>
            <div className="pb-5">
                <DataTable title="Endpoint Activity" description="Time series of all endpoint activities" columns={endpointActivityColumns} data={data} />
            </div>
        </div>
    );
}