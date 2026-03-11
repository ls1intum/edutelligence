# Bruno Collection: Logos Node Provider

Import folder:

`docs/bruno/node-provider`

Then select environment:

`environments/local`

For HTTP-only local dev (no TLS):

`environments/local-http-dev`

## Variables to set first

- `baseUrl` (Logos HTTPS URL)
- `logosKey` (root logos key)
- `processId` (from `Get Process ID`)
- `profileId` (from `Add Profile`, or existing one)
- `modelId` and `modelName`
- `providerId` and `sharedKey` (from `Register Node Provider`)
- `nodeId`
- `laneId` (for lane operations)

## Recommended request order

1. `01 Identity/Get Process ID`
2. `01 Identity/Add Profile (Optional)`
3. `02 Model+Provider/List Models`
4. `02 Model+Provider/Add Model (Optional)`
5. `02 Model+Provider/Register Node Provider`
6. `02 Model+Provider/Connect Model Provider`
7. `02 Model+Provider/Connect Profile Model`
8. Configure node `config.yml` with `providerId/sharedKey`
9. Start node
10. `03 Runtime/Auth Node (Handshake Test)`
11. `03 Runtime/Get Node Status`
12. `03 Runtime/Get Node GPU`
13. `03 Runtime/Get Node Lanes`
14. Lane operation requests in `04 Lane Control`
15. `05 Inference/V1 Chat Completions`

## Important

- `Auth Node (Handshake Test)` only validates provider credentials and returns a short-lived websocket ticket.
- Actual persistent websocket session is initiated by the node process itself.
- Use HTTPS base URL. Node auth/session are TLS-enforced.
- HTTP dev mode works only if both are explicitly enabled:
- Logos env: `LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP=true`
- Node config: `logos.allow_insecure_http: true`
