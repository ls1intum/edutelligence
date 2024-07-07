export type ModuleMeta = {
  name: string;
  type: string;
  healthy: boolean;
  supportsEvaluation: boolean;
  supportsNonGradedFeedbackRequests: boolean;
};

export type HealthResponse = {
  status: string;
  modules: {
    [key: string]: ModuleMeta;
  };
};
