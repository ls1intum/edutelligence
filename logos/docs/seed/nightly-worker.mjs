// Documentation telemetry only. Use the isolated screenshots stack and seed.
// Requires Node.js 22+. No inference or worker-control command is executed.
const origin = 'http://localhost:19080';
const model = 'llama-3.1-8b-instruct';
const response = await fetch(`${origin}/logosdb/providers/logosnode/auth`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    shared_key: 'docs-role-screenshots-worker',
    capabilities_models: [model],
    configured_models: [model],
  }),
});
if (!response.ok) throw new Error(`Worker authentication failed: ${response.status}`);
const { session_token } = await response.json();
const ws = new WebSocket(`${origin.replace('http:', 'ws:')}/logosdb/providers/logosnode/session?token=${encodeURIComponent(session_token)}`);
let timer;
ws.addEventListener('open', () => {
  const sendStatus = () => ws.send(JSON.stringify({
    type: 'status',
    runtime: {
      supports_benchmark_restart: true,
      devices: {
        nvidia_smi_available: true,
        devices: [{ kind: 'nvidia', name: 'Documentation GPU', memory_total_mb: 46080 }],
      },
      lanes: [{
        lane_id: 'docs-lane', model, backend: 'vllm', loaded: true, sleeping: false,
        lane_config: { vllm_config: { max_num_seqs: 16, max_num_batched_tokens: 4096 } },
      }],
    },
  }));
  ws.send(JSON.stringify({ type: 'hello', worker_id: 'Docs Local Worker', capabilities_models: [model], configured_models: [model] }));
  sendStatus();
  timer = setInterval(sendStatus, 5000);
  console.log('Documentation worker connected. Stop with Ctrl+C after capture.');
});
ws.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data);
  if (message.type === 'command') ws.send(JSON.stringify({
    type: 'command_result', cmd_id: message.cmd_id, success: false,
    error: 'Documentation worker: commands are disabled',
  }));
});
ws.addEventListener('error', () => { throw new Error('Documentation worker connection failed'); });
ws.addEventListener('close', () => { clearInterval(timer); });
process.on('SIGINT', () => { clearInterval(timer); ws.close(); });
