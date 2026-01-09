-- Migration: Point TUM GPU endpoints to local Ollama (via host.docker.internal)
-- TODO: Adjust the endpoint url based off the new local Ollama hosting setup

UPDATE models
SET endpoint = 'http://host.docker.internal:11435/api/chat'
WHERE endpoint LIKE '%aet.cit.tum.de%';
