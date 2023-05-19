export type ModuleMeta = {
    name: string;
    type: string;
    healthy: boolean;
};

type HealthResponse = {
    status: string;
    modules: {
        [key: string]: ModuleMeta;
    };
};

export default HealthResponse;