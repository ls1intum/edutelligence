import type { ModuleMeta } from '@/model/health_response';

import { ReactNode, createContext, useContext, useReducer } from 'react';

export type Module = {
  module?: ModuleMeta;
  moduleConfig: any;
};

type ModuleAction =
  | { type: 'SET_MODULE'; payload: ModuleMeta }
  | { type: 'SET_MODULE_CONFIG'; payload: any };

const initialModuleInfo: Module = {
  module: undefined,
  moduleConfig: {},
};

const ModuleContext = createContext<{
  state: Module,
  dispatch: React.Dispatch<ModuleAction>
}>({ state: initialModuleInfo, dispatch: () => null });

function moduleReducer(state: Module, action: ModuleAction): Module {
  switch (action.type) {
    case "SET_MODULE":
      return { ...state, module: action.payload };
    case "SET_MODULE_CONFIG":
      return { ...state, moduleConfig: action.payload };
    default:
      throw new Error(`Unhandled action type: ${action}`);
  }
}

function ModuleProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(moduleReducer, initialModuleInfo);
  return (
    <ModuleContext.Provider value={{ state, dispatch }}>
      {children}
    </ModuleContext.Provider>
  );
};

function useModule(): Module {
  const context = useContext(ModuleContext);
  if (context === undefined) {
    throw new Error('useModule must be used within a ModuleProvider');
  }
  return context.state;
}

function useModuleDispatch(): React.Dispatch<ModuleAction> {
  const context = useContext(ModuleContext);
  if (context === undefined) {
    throw new Error('useModuleDispatch must be used within a ModuleProvider');
  }
  return context.dispatch;
}

export { ModuleProvider, useModule, useModuleDispatch };
