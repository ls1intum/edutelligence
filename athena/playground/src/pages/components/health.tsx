import useSWR from "swr";
import fetcher from "@/pages/fetcher";
import HealthResponse from "@/pages/model/health_response";

export default function Health(
    { url }: { url: string }
) {
    // show red and green dots for module health
    const { data, error } = useSWR<HealthResponse>("api/health?url=" + encodeURIComponent(url), fetcher);
    if (error) return <div>failed to load</div>;
    if (!data) return <div>loading...</div>;
    return (
        <div className="flex flex-col mt-4">
            <span className="text-lg font-bold">Health</span>
            <div className="flex flex-row items-center">
                <span className={data.status === "ok" ? "bg-green-500 rounded-full w-4 h-4" : "bg-red-500 rounded-full w-4 h-4"}></span>
                <span className="ml-1">Assessment Module Manager</span>
            </div>
            <div className="flex flex-col">
                {Object.entries(data.modules).map(([name, {healthy}]) => (
                    <div className="flex flex-row items-center" key={name}>
                        <span className={healthy ? "bg-green-500 rounded-full w-4 h-4" : "bg-red-500 rounded-full w-4 h-4"}></span>
                        <span className="ml-1">{name}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}