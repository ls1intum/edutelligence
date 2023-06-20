import Health from "@/components/health";
import ModuleSelect from "@/components/selectors/module_select";
import { ModuleMeta } from "@/model/health_response";
import { Mode } from "@/model/mode";
import DataSelect from "./selectors/data_select";

type BaseInfoHeaderProps = {
  athenaUrl: string;
  onChangeAthenaUrl: (value: string) => void;
  athenaSecret: string;
  onChangeAthenaSecret: (value: string) => void;
  module: ModuleMeta | undefined;
  onChangeModule: (value: ModuleMeta) => void;
  mode: Mode;
  onChangeMode: (value: Mode) => void;
};

export default function BaseInfoHeader({
  athenaUrl,
  onChangeAthenaUrl,
  athenaSecret,
  onChangeAthenaSecret,
  module,
  onChangeModule,
  mode,
  onChangeMode,
}: BaseInfoHeaderProps) {
  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <label className="flex flex-col">
        <span className="text-lg font-bold">Athena URL</span>
        <input
          className="border border-gray-300 rounded-md p-2"
          value={athenaUrl}
          onChange={(e) => onChangeAthenaUrl(e.target.value)}
        />
      </label>
      <Health url={athenaUrl} />
      <label className="flex flex-col mt-4">
        <span className="text-lg font-bold">Secret</span>
        <p className="text-gray-500 mb-2">
          This is the secret that you configured in Athena. It&apos;s optional
          for local development, but required for production setups.
        </p>
        <input
          className="border border-gray-300 rounded-md p-2"
          value={athenaSecret}
          placeholder="Optional, only required for production setups"
          onChange={(e) => onChangeAthenaSecret(e.target.value)}
        />
      </label>
      <br />
      <ModuleSelect url={athenaUrl} module={module} onChange={onChangeModule} />
      <br />
      <DataSelect mode={mode} onChangeMode={onChangeMode} />
    </div>
  );
}
