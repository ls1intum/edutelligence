import useSWR from "swr";
import fetcher from "@/helpers/fetcher";
import HealthResponse, {ModuleMeta} from "@/model/health_response";
import baseUrl from "@/helpers/base_url";

export default function ModuleSelect(
    { url, module, onChange }: { url: string, module: ModuleMeta | undefined, onChange: (module: ModuleMeta) => void }
) {
    const { data, error } = useSWR<HealthResponse>(`${baseUrl}/api/health?url=${encodeURIComponent(url)}`, fetcher);
    if (error) return <div>failed to load</div>;
    if (!data) return <div>loading...</div>;
    return (
        <label className="flex flex-col">
            <span className="text-lg font-bold">Module</span>
            <select className="border border-gray-300 rounded-md p-2" value={module?.name ?? ""} onChange={e => onChange(data.modules[e.target.value])}>
                <option value={""} disabled>Select a module</option>
                {
                    Object.entries(data.modules)
                        .map(([moduleName, {healthy, type}]) => {
                            return <option key={moduleName} value={moduleName}>
                                {moduleName}{healthy ? '' : ' (not healthy!)'}
                            </option>;
                        })}
            </select>
        </label>
    );
}
