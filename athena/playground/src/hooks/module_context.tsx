import type { ModuleMeta } from '@/model/health_response';

import { ReactNode, createContext, useContext, useReducer } from 'react';

type Module = {
  module: ModuleMeta;
  moduleConfig: any;
};

const ModuleContext = createContext<Module | undefined>(undefined);

type ModuleProviderProps = {
  module: ModuleMeta;
  moduleConfig: any;
  children: ReactNode;
};

function ModuleProvider({ module, moduleConfig, children }: ModuleProviderProps) {
  return (
    <ModuleContext.Provider value={{ module, moduleConfig }}>
      {children}
    </ModuleContext.Provider>
  );
};

function useModule(): Module {
  const context = useContext(ModuleContext);
  if (context == undefined) {
    throw new Error('useModule must be used within a ModuleProvider');
  }
  return context;
}

export { ModuleProvider, useModule };