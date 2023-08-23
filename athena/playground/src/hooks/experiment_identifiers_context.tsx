import { ReactNode, createContext, useContext } from 'react';

export type ExperimentIdentifiers = {
  experimentId?: string;
  moduleConfigurationId?: string;
  runId?: string;
};

const ExperimentIdentifiersContext = createContext<{
  state: ExperimentIdentifiers, 
}>({
  state: {
    experimentId: undefined,
    moduleConfigurationId: undefined,
    runId: undefined,
  }
});

function ExperimentIdentifiersProvider({ children, experimentIdentifiers }: { children: ReactNode, experimentIdentifiers: ExperimentIdentifiers }) {
  return (
    <ExperimentIdentifiersContext.Provider value={{ state: experimentIdentifiers }}>
      {children}
    </ExperimentIdentifiersContext.Provider>
  );
};

function useExperimentIdentifiers(): ExperimentIdentifiers {
  const context = useContext(ExperimentIdentifiersContext);
  if (context == undefined) {
    return {
      experimentId: undefined,
      moduleConfigurationId: undefined,
      runId: undefined,
    };
  }
  return context.state;
}

export { ExperimentIdentifiersProvider, useExperimentIdentifiers };