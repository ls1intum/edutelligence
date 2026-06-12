# Bruno Collection: LogosWorkerNode Provider

Use this collection to bootstrap and operate a `logosnode` provider from a local Bruno environment.

Required environment values:
- `baseUrl`
- `logosKey`
- `providerId`
- `sharedKey`
- `workerId`
- `modelId`
- `modelName`
- `profileId`
- `laneId`

Recommended flow:
1. `01 Identity/Get Process ID`
2. `02 Model+Provider/Get Models`
3. `02 Model+Provider/Register LogosWorkerNode Provider`
4. `02 Model+Provider/Connect Model Provider`
5. `02 Model+Provider/Connect Profile Model`
6. `03 Runtime/Auth Node Handshake Test`
7. `03 Runtime/Get Node Status`
8. `04 Lane Control/*`
9. `05 Inference/v1 Chat Completions`

All provider-control endpoints now live under `/logosdb/providers/logosnode/*`.
