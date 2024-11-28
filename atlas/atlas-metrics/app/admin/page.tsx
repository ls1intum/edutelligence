import { Menu } from "@components/custom/Menu";
import { DataTable } from "@components/custom/DataTable";
import applicationContainer from "@server/applicationContainer";
import { endpointActivityColumns } from "./columns";

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
