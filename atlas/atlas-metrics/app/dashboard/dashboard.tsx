import { EndpointActivity } from "@components/custom/EndpointActivity";
import { PieChartDonut } from "@components/custom/PieChartDonut";
import { Menu } from "@components/custom/Menu";
import {useEffect, useState} from "react";
import {DashboardDataDAO, DashboardDataSchema} from "@server/domain/dao/dashboardData";

export default function Dashboard() {

  const [metrics, setMetrics] = useState<DashboardDataDAO|undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchMetrics() {
      try {
        const response = await fetch("/api/data/dashboard");
        const data = await response.json();
        const parsed = DashboardDataSchema.safeParse(data);

        if (parsed.success) {
          setMetrics(parsed.data);
        } else {
          setError(`Invalid response type: ${parsed.error}`);
        }
      } catch (error) {
        setError((error as Error).message);
      }
    }

    fetchMetrics().finally(() => setLoading(false));
  }, []);

    if (loading) {
        return <div>Loading...</div>;
    }

  if (error) {
    return <p>Error: {error}</p>;
  }

  return (
    <div className="m-5 min-h-screen text-center">
      <Menu />
      <div className="pb-5">
        <EndpointActivity
          title="Endpoint Activity"
          description="Recent activity for all endpoints of Atlas"
          chartData={metrics!.endpointActivity.timeSeries}
        />
      </div>
      <div className="grid grid-cols-2 gap-5 pb-10">
        <PieChartDonut
          title="Activity by Type"
          description="Activity grouped by the type of endpoints"
          label="Calls"
          chartData={metrics!.endpointActivity.byType}
        />
        <PieChartDonut
          title="Activity by Category"
          description="Activity grouped by category of endpoints"
          label="Calls"
          chartData={metrics!.endpointActivity.byCategory}
        />
      </div>
    </div>
  );
}
