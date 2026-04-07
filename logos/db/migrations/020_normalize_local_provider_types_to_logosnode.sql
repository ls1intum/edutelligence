UPDATE providers
SET provider_type = 'logosnode'
WHERE provider_type IN ('ollama', 'node', 'node_controller', 'logos_worker_node', 'logos-workernode');
