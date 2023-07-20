export type ModuleMeta = {
  name: string;
  type: string;
  healthy: boolean;
};

export type HealthResponse = {
  status: string;
  modules: {
    [key: string]: ModuleMeta;
  };
};
