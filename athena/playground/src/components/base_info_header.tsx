import { useBaseInfo, useBaseInfoDispatch } from "@/hooks/base_info_context";

import Health from "@/components/health";
import DataModeSelect from "@/components/selectors/data_mode_select";
import ViewModeSelect from "@/components/selectors/view_mode_select";

export default function BaseInfoHeader() {
  const { dataMode, viewMode, athenaUrl, athenaSecret } = useBaseInfo();
  const dispatch = useBaseInfoDispatch();

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <label className="flex flex-col">
        <span className="text-lg font-bold">Athena URL</span>
        <input
          className="border border-gray-300 rounded-md p-2"
          value={athenaUrl}
          onChange={(e) => dispatch({ type: "SET_ATHENA_URL", payload: e.target.value })}
        />
      </label>
      <Health />
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
          onChange={(e) => dispatch({ type: "SET_ATHENA_SECRET", payload: e.target.value })}
        />
      </label>
      <br />
      <DataModeSelect 
        dataMode={dataMode} 
        onChangeDataMode={(dataMode) => dispatch({ type: "SET_DATA_MODE", payload: dataMode })} 
      />
      <br />
      <ViewModeSelect 
        viewMode={viewMode} 
        onChangeViewMode={(viewMode) => dispatch({ type: "SET_VIEW_MODE", payload: viewMode })} 
      />
    </div>
  );
}
