import Health from "@/pages/components/health";
import ModuleSelect from "@/pages/components/module_select";
import {ModuleMeta} from "@/pages/model/health_response";

export default function BaseInfoHeader(
    {athenaUrl, onChangeAthenaUrl, module, onChangeModule}: {
        athenaUrl: string,
        onChangeAthenaUrl: (value: string) => void,
        module: ModuleMeta | undefined,
        onChangeModule: (value: ModuleMeta) => void
    }
) {
    return (
        <div className="bg-white rounded-md p-4">
            <label className="flex flex-col">
                <span className="text-lg font-bold">Athena URL</span>
                <input className="border border-gray-300 rounded-md p-2" value={athenaUrl}
                       onChange={e => onChangeAthenaUrl(e.target.value)}/>
            </label>
            <Health url={athenaUrl}/>
            <br />
            <ModuleSelect url={athenaUrl} module={module} onChange={onChangeModule} />
        </div>
    );
}