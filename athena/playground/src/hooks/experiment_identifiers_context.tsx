import { ReactNode, createContext, useContext, useState } from "react";

export type ExperimentIdentifiers = {
  experimentId?: string;
  moduleConfigurationId?: string;
  runId?: string;
};

const ExperimentIdentifiersContext = createContext<{
  state: ExperimentIdentifiers;
  setRunId: (runId: string | undefined) => void;
}>({
  state: {
    experimentId: undefined,
    moduleConfigurationId: undefined,
    runId: undefined,
  },
  setRunId: () => null,
});

function ExperimentIdentifiersProvider({
  children,
  experimentIdentifiers,
}: {
  children: ReactNode;
  experimentIdentifiers: ExperimentIdentifiers;
}) {
  const [runId, setRunId] = useState(experimentIdentifiers.runId)

  return (
    <ExperimentIdentifiersContext.Provider
      value={{ state: {
        ...experimentIdentifiers,
        runId,
      },
      setRunId
    }}
    >
      {children}
    </ExperimentIdentifiersContext.Provider>
  );
}

function useExperimentIdentifiers() {
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

function useExperimentIdentifiersSetRunId() {
  const context = useContext(ExperimentIdentifiersContext);
  if (context == undefined) {
    throw new Error('useExperimentIdentifiersSetRunId must be used within an ExperimentIdentifiersContext');
  }
  return context.setRunId;
}

export { ExperimentIdentifiersProvider, useExperimentIdentifiers, useExperimentIdentifiersSetRunId };
