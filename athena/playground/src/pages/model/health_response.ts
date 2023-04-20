type HealthResponse = {
    status: string;
    modules: {
        [key: string]: {
            name: string;
            healthy: boolean;
        };
    };
};

export default HealthResponse;