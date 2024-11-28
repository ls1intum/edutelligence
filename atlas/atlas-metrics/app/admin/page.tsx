import { Menu } from "@/components/custom/menu";
import { DataTable } from "@/components/custom/data-table";
import { endpointActivityColumns } from "@/app/admin/columns";
import applicationContainer from "@/app/server/applicationContainer";

export default async function Admin() {
  const metricsService = applicationContainer.getMetricsService();
  const data = await metricsService.getEndpointActivity();
  return (
    <div className="m-5 text-center">
      <div className="pb-5">
        <Menu />
      </div>
      <div className="pb-5">
        <DataTable
          title="Endpoint Activity"
          description="Time series of all endpoint activities"
          columns={endpointActivityColumns}
          data={data}
        />
      </div>
    </div>
  );
}
