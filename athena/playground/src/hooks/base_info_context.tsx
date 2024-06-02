import type { DataMode } from '@/model/data_mode';
import type { ViewMode } from '@/model/view_mode';

import { ReactNode, createContext, useContext, useReducer } from 'react';

export type BaseInfo = {
  athenaUrl: string;
  athenaSecret: string;
  lmsUrl: string;
  dataMode: DataMode;
  viewMode: ViewMode;
};

type Action =
  | { type: 'SET_ATHENA_URL'; payload: string }
  | { type: 'SET_ATHENA_SECRET'; payload: string }
  | { type: 'SET_LMS_URL'; payload: string }
  | { type: 'SET_DATA_MODE'; payload: DataMode }
  | { type: 'SET_VIEW_MODE'; payload: ViewMode };

function createInitialState(): BaseInfo {
  let athenaUrl = "http://127.0.0.1:5000";
  let lmsUrl = "http://localhost:3000";
  if (
    typeof window !== "undefined" &&
    window.location.hostname !== "localhost"
  ) {
    // athena url for non-local development is the origin of the current page
    athenaUrl = window.location.origin;
    // lms url for non-local development is the origin of the current page
    lmsUrl = window.location.origin;
  }
  return {
    athenaUrl: athenaUrl,
    athenaSecret: "",
    lmsUrl: lmsUrl,
    dataMode: "example",
    viewMode: "module_requests",
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
      return { ...state, athenaUrl: action.payload };
    case "SET_LMS_URL":
      return { ...state, lmsUrl: action.payload };
    case "SET_ATHENA_SECRET":
      return { ...state, athenaSecret: action.payload };
    case "SET_DATA_MODE":
      return { ...state, dataMode: action.payload };
    case "SET_VIEW_MODE":
        return { ...state, viewMode: action.payload };
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
  if (context == undefined) {
    throw new Error('useBaseInfoState must be used within a BaseInfoProvider');
  }
  return context.state;
}

function useBaseInfoDispatch(): React.Dispatch<Action> {
  const context = useContext(BaseInfoContext);
  if (context == undefined) {
    throw new Error('useBaseInfoDispatch must be used within a BaseInfoProvider');
  }
  return context.dispatch;
}

export { BaseInfoProvider, useBaseInfo, useBaseInfoDispatch };