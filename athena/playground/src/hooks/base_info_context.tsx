import type { Mode } from '@/model/mode';
import type { ModuleMeta } from '@/model/health_response';

import { ReactNode, createContext, useContext, useReducer } from 'react';

export type BaseInfo = {
  athenaUrl: string;
  athenaSecret: string;
  module?: ModuleMeta;
  moduleConfig: any;
  mode: Mode;
};

type Action =
  | { type: 'SET_ATHENA_URL'; payload: string }
  | { type: 'SET_ATHENA_SECRET'; payload: string }
  | { type: 'SET_MODULE'; payload: ModuleMeta }
  | { type: 'SET_MODULE_CONFIG'; payload: any }
  | { type: 'SET_MODE'; payload: Mode };

function createInitialState(): BaseInfo {
  let defaultUrl = "http://127.0.0.1:5000";
  if (
    typeof window !== "undefined" &&
    window.location.hostname !== "localhost"
  ) {
    // default url for non-local development is the origin of the current page
    defaultUrl = window.location.origin;
  }
  return {
    athenaUrl: defaultUrl,
    athenaSecret: "",
    module: undefined,
    moduleConfig: {},
    mode: "example",
  };
}

const BaseInfoContext = createContext<{
  state: BaseInfo, 
  dispatch: React.Dispatch<Action>
}>({
  state: createInitialState(), 
  dispatch: () => null
});

function reducer(state: BaseInfo, action: Action): BaseInfo {
  switch (action.type) {
    case "SET_ATHENA_URL":
      return { ...state, athenaUrl: action.payload, module: undefined, moduleConfig: undefined };
    case "SET_ATHENA_SECRET":
      return { ...state, athenaSecret: action.payload };
    case "SET_MODULE":
      return { ...state, module: action.payload, moduleConfig: undefined };
    case "SET_MODULE_CONFIG":
      return { ...state, moduleConfig: action.payload };
    case "SET_MODE":
      return { ...state, mode: action.payload };
    default:
      throw new Error(`Unhandled action: ${action}`);
  }
}

function BaseInfoProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, createInitialState());

  return (
    <BaseInfoContext.Provider value={{ state, dispatch }}>
      {children}
    </BaseInfoContext.Provider>
  );
};

function useBaseInfo(): BaseInfo {
  const context = useContext(BaseInfoContext);
  if (context === undefined) {
    throw new Error('useBaseInfoState must be used within a BaseInfoProvider');
  }
  return context.state;
}

function useBaseInfoDispatch(): React.Dispatch<Action> {
  const context = useContext(BaseInfoContext);
  if (context === undefined) {
    throw new Error('useBaseInfoDispatch must be used within a BaseInfoProvider');
  }
  return context.dispatch;
}

export { BaseInfoProvider, useBaseInfo, useBaseInfoDispatch };