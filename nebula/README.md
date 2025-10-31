# Nebula

This is the central orchestration repository for all Nebula services - an intelligent microservices platform for automated educational content processing.

## 🎯 What is Nebula?

Nebula is a sophisticated microservices-based platform designed for automated lecture video processing and educational content enhancement. The system provides:

- **🎥 Transcription Service**: Automated video transcription with intelligent slide detection
- **❓ FAQ Service**: Educational content quality assurance and consistency checking

### Key Features

#### Transcription Service

- **Automated Video Processing**: Process `.m3u8` lecture video streams with 95%+ accuracy
- **Intelligent Slide Detection**: Computer vision-based slide number identification using GPT-4o Vision
- **FIFO Queue System**: Ordered processing with First-In-First-Out guarantee
- **Two-Phase Pipeline**: Optimized separation of heavy sequential operations and light parallel tasks
- **Chunked Processing**: Automatic audio splitting for optimal Whisper API processing
- **Timestamp Alignment**: Precise slide number alignment with transcript segments

#### FAQ Service

- **Text Rewriting**: AI-powered FAQ enhancement for educational platforms
- **Consistency Checking**: Automated contradiction detection and quality assurance

## 🚀 Quick Start for Developers

This guide will help you get the Nebula services running locally for development.

### Prerequisites

- Python 3.10-3.12
- Poetry (Python package manager)
- Docker Desktop (nginx uses `openresty/openresty` image)
- FFmpeg (for transcription service)
- Git

### Step 1: Clone and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/nebula

# Install Python dependencies
poetry install

# Copy example configurations
cp llm_config.example.yml llm_config.local.yml
cp nginx.local_example.conf nginx.local.conf
```

### Step 2: Configure LLM Settings

Edit `llm_config.local.yml` with your API keys and endpoints:

```yaml
llms:
  - id: "azure-gpt-4-omni"
    type: "azure_openai"
    api_key: "YOUR_API_KEY" # pragma: allowlist secret
    endpoint: "YOUR_ENDPOINT"
    # ... other settings
```

### Step 3: Start Services Locally

Open **three separate terminals** for the services:

**Terminal 1 - Transcriber Service (Port 3870):**

```bash
cd edutelligence/nebula
poetry run uvicorn nebula.transcript.app:app --host 0.0.0.0 --port 3870 --reload
```

**Terminal 2 - FAQ Service (Port 3871):**

```bash
cd edutelligence/nebula
poetry run uvicorn nebula.faq.app:app --host 0.0.0.0 --port 3871 --reload
```

**Terminal 3 - Nginx Gateway (Port 3007):**

```bash
cd edutelligence/nebula
# Clean up any existing containers first
docker compose -f docker/nginx-only.yml down
docker rm -f nebula-nginx-gateway 2>/dev/null || true

# Start nginx gateway
docker compose -f docker/nginx-only.yml up
```

### Step 4: Verify Everything is Running

```bash
# Check health status (should return JSON with service statuses)
curl http://localhost:3007/health

# Test transcriber endpoint (requires API key)
curl -H "Authorization: nebula-secret" http://localhost:3007/transcribe/health

# Test FAQ endpoint (requires API key)
curl -H "Authorization: nebula-secret" http://localhost:3007/faq/health
```

### Step 5: Submit a Transcription Job

```bash
# Submit a video for transcription
curl -X POST http://localhost:3007/transcribe/start \
  -H "Authorization: nebula-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "videoUrl": "https://live.rbg.tum.de/w/test/12345.m3u8",
    "lectureUnitId": 456
  }'

# Response will include a job ID:
# {"status": "processing", "transcriptionId": "550e8400-e29b-41d4-a716-446655440000"}

# Check job status (replace {job_id} with the transcriptionId from above)
curl -H "Authorization: nebula-secret" \
  http://localhost:3007/transcribe/status/{job_id}
```

### Development Workflow

1. **Services run locally with hot reload** - Any changes to Python files automatically restart the service
2. **Nginx provides API gateway** - Handles authentication, routing, and health checks
3. **Access all services through port 3007** - Single entry point for all APIs
4. **FIFO Queue Processing** - Jobs are processed in order, ensuring resource efficiency

### Troubleshooting

#### General Issues

- **Port already in use**: Make sure ports 3870, 3871, and 3007 are free
- **Connection refused**: Ensure all services are running in their respective terminals
- **Unauthorized errors**: Check the API key in `nginx.local.conf` matches what you're sending (default: `nebula-secret`)
- **Module not found**: Run `poetry install` to ensure all dependencies are installed

#### Nginx Gateway Issues

- **Nginx container exits immediately**:
  - Remove old containers: `docker rm -f nebula-nginx-gateway`
  - Check logs: `docker compose -f docker/nginx-only.yml logs`
  - Ensure `nginx.local.conf` exists and has correct syntax
- **"host not found in upstream" errors**: Your `nginx.local.conf` might be outdated. Copy the latest example:
  ```bash
  cp nginx.local_example.conf nginx.local.conf
  ```

#### Transcription Service Issues

- **FFmpeg not found**: Install FFmpeg and ensure it's in your system PATH
  - macOS: `brew install ffmpeg`
  - Windows: Download from https://ffmpeg.org/download.html
  - Linux: `apt-get install ffmpeg`
- **Job stuck in processing**: Check transcriber service logs for errors, verify Azure OpenAI credentials
- **404 from GPT Vision**: Verify GPT-4o Vision deployment name and API version in `llm_config.local.yml`
- **Memory issues**: Ensure sufficient disk space for temp files (500MB-2GB per video)

## 🏗️ Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        External Services                        │
├─────────────────┬─────────────────┬─────────────────────────────┤
│   TUM-Live      │  Azure OpenAI   │      OpenAI                 │
│ Video Streaming │ GPT-4o & Whisper│   GPT-4o & Whisper         │
└─────────────────┴─────────────────┴─────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Gateway Layer                            │
│              Nginx Gateway (Port 3007)                          │
│           - API Key Authentication                              │
│           - Request Routing                                     │
│           - Health Monitoring                                   │
└─────────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────────┐  ┌────────────────────────┐
│  Transcriber Service     │  │    FAQ Service         │
│     (Port 3870)          │  │    (Port 3871)         │
│  - FIFO Job Queue        │  │  - Text Rewriting      │
│  - Two-Phase Pipeline    │  │  - Consistency Check   │
│  - Slide Detection       │  │                        │
└──────────────────────────┘  └────────────────────────┘
```

### Transcription Service Architecture

The transcription service uses a sophisticated **two-phase processing pipeline** with **FIFO queue management**:

#### FIFO Queue System

```
Job Submission → FIFO Queue → Background Worker → Heavy Pipeline → Light Pipeline
     │               │              │                   │                │
     │               │              │                   │                └─→ Parallel per job
     │               │              │                   └─→ Sequential (one at a time)
     │               │              └─→ Dequeues jobs in strict order
     │               └─→ Jobs wait in order (Job 1 → Job 2 → Job 3)
     └─→ Immediate response with job ID
```

**Key Benefits:**

- **Ordered Processing**: Jobs are processed in the exact order received
- **Resource Management**: Heavy operations (video download, audio extraction) run one at a time
- **Parallel Optimization**: Light operations (frame analysis) run concurrently for different jobs
- **Responsive API**: Job submission returns immediately with a job ID

#### Phase 1: Heavy Pipeline (Sequential)

Processes one job at a time to avoid resource contention:

1. **Video Download** (2-5 min)
   - Downloads `.m3u8` stream using FFmpeg
   - Stores as MP4 in temporary storage

2. **Audio Extraction** (20-30 sec)
   - Extracts audio track from video
   - Converts to WAV format for Whisper

3. **Audio Chunking** (instant)
   - Splits audio into 180-second segments
   - Optimizes for Whisper API rate limits

4. **Whisper Transcription** (5-10 min)
   - Processes chunks sequentially
   - Implements retry logic with exponential backoff
   - Aggregates results with timestamp alignment

#### Phase 2: Light Pipeline (Parallel per Job)

Runs concurrently for each job after heavy pipeline completes:

1. **Frame Extraction** (30-60 sec)
   - Extracts frames at transcript segment timestamps
   - Crops bottom 5% of each frame (slide number region)

2. **GPT Vision Analysis** (2-3 min)
   - Sends cropped frames to GPT-4o Vision
   - Detects slide numbers with AI
   - Throttles requests (2-second delay)

3. **Alignment** (instant)
   - Aligns detected slide numbers with transcript segments
   - Uses timestamp-based matching algorithm

4. **Result Storage** (instant)
   - Saves final transcription to memory cache
   - Sets 60-minute TTL for result expiration

### Data Flow

```
Client Request
    ↓
POST /transcribe/start
    ↓
Create Job ID
    ↓
Enqueue to FIFO Queue ────→ Return {"transcriptionId": "..."}
    ↓
Background Worker Dequeues
    ↓
Heavy Pipeline (Sequential)
├─ Download Video
├─ Extract Audio
├─ Chunk Audio
└─ Transcribe with Whisper
    ↓
Light Pipeline (Parallel) ────→ Other jobs can start Heavy Pipeline
├─ Extract Frames
├─ Detect Slides (GPT Vision)
├─ Align with Transcript
└─ Save Result
    ↓
Client Polls: GET /transcribe/status/{job_id}
    ↓
Receive Complete Transcription with Slide Numbers
```

### API Endpoints Summary

#### Transcription Service

| Endpoint                      | Method | Description              | Response         |
| ----------------------------- | ------ | ------------------------ | ---------------- |
| `/transcribe/start`           | POST   | Submit transcription job | Job ID           |
| `/transcribe/status/{job_id}` | GET    | Check job status         | Status or result |
| `/transcribe/health`          | GET    | Service health check     | Health status    |

#### FAQ Service

| Endpoint                 | Method | Description           | Response           |
| ------------------------ | ------ | --------------------- | ------------------ |
| `/faq/rewrite-faq`       | POST   | Rewrite FAQ text      | Improved text      |
| `/faq/check-consistency` | POST   | Check FAQ consistency | Consistency report |
| `/faq/health`            | GET    | Service health check  | Health status      |

### Technology Stack

- **Web Framework**: FastAPI (Python 3.12+)
- **API Gateway**: Nginx with OpenResty (Lua scripting)
- **AI Services**: Azure OpenAI (GPT-4o Vision, Whisper), OpenAI
- **Media Processing**: FFmpeg, OpenCV, PyDub
- **Containerization**: Docker & Docker Compose
- **Queue Management**: asyncio.Queue (Python native)

## 🚢 Production Deployment

This guide covers deploying Nebula services in a production environment.

### Prerequisites

- Docker and Docker Compose installed on the server
- SSL certificates for HTTPS
- Domain name configured with DNS pointing to your server
- Access to container registry (GitHub Container Registry)

### Step 1: Prepare Configuration Files

```bash
# Clone the repository on your production server
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/nebula

# Copy and configure production files
cp .env.production-example .env
cp nginx.compose_example.conf nginx.production.conf
cp llm_config.example.yml llm_config.production.yml

# Edit the .env file with your production values
nano .env
# Update these key variables:
# - NEBULA_NGINX_CONFIG_FILE=./nginx.production.conf
# - NEBULA_LLM_CONFIG_FILE=./llm_config.production.yml
# - NEBULA_TEMP_DIR with your desired temp directory
```

### Step 2: Configure Nginx for Production

Edit `nginx.production.conf`:

```nginx
# Update API key (line ~26)
"your-production-api-key" 1;  # CHANGE THIS

# Update server name (line ~50)
server_name api.yourdomain.com;  # CHANGE THIS

# Enable HTTPS (uncomment lines ~54, ~61-62)
listen 443 ssl http2;
ssl_certificate /path/to/your/certificate.crt;
ssl_certificate_key /path/to/your/private.key;

# Optional: Enable HTTPS redirect (uncomment lines ~78-80)
if ($scheme = http) {
    return 301 https://$server_name$request_uri;
}
```

### Step 3: Configure LLM Settings

Edit `llm_config.production.yml` with your production API credentials:

```yaml
llms:
  - id: "azure-gpt-4-omni"
    type: "azure_openai"
    api_key: "${AZURE_API_KEY}" # Can use environment variables # pragma: allowlist secret
    endpoint: "${AZURE_ENDPOINT}"
    api_version: "2024-02-15-preview"
    deployment: "gpt-4-omni"
```

### Step 4: Deploy with Docker Compose

```bash
# Pull latest images (if using pre-built images)
docker compose -f docker/nebula-production.yml pull

# Or build locally
docker compose -f docker/nebula-production.yml build

# Start all services
docker compose -f docker/nebula-production.yml up -d

# Check logs
docker compose -f docker/nebula-production.yml logs -f

# Verify deployment
curl https://api.yourdomain.com/health
```

### Step 5: Set Up SSL/TLS (Using Let's Encrypt)

For automatic SSL with Let's Encrypt, you can use Certbot:

```bash
# Install Certbot
apt-get update
apt-get install certbot

# Get certificates
certbot certonly --standalone -d api.yourdomain.com

# Update nginx.production.conf with cert paths
ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

# Restart nginx
docker compose -f docker/nebula-production.yml restart nginx
```

### Production Monitoring

#### Health Checks

```bash
# Check overall system health
curl https://api.yourdomain.com/health

# Monitor logs
docker compose -f docker/nebula-production.yml logs -f

# Check individual service logs
docker logs transcriber-service
docker logs faq-service
docker logs nginx-proxy
```

#### Service Management

```bash
# Stop services
docker compose -f docker/nebula-production.yml down

# Restart services
docker compose -f docker/nebula-production.yml restart

# Update services
docker compose -f docker/nebula-production.yml pull
docker compose -f docker/nebula-production.yml up -d

# Scale services (if needed)
docker compose -f docker/nebula-production.yml up -d --scale transcriber=2
```

### Security Considerations

1. **API Keys**: Use strong, unique API keys in production
2. **HTTPS**: Always use HTTPS in production with valid SSL certificates
3. **Firewall**: Configure firewall to only allow ports 80, 443
4. **Updates**: Regularly update Docker images and dependencies
5. **Secrets**: Use environment variables or secret management for sensitive data
6. **Rate Limiting**: Consider adding rate limiting in nginx configuration
7. **Monitoring**: Set up monitoring and alerting for service health

### Backup and Recovery

```bash
# Backup configuration files
tar -czf nebula-config-backup.tar.gz \
  nginx.production.conf \
  llm_config.production.yml \
  .env

# Backup any persistent data
docker compose -f docker/nebula-production.yml exec transcriber \
  tar -czf /backup/transcriber-data.tar.gz /app/temp

# Restore from backup
tar -xzf nebula-config-backup.tar.gz
docker compose -f docker/nebula-production.yml up -d
```

### Troubleshooting Production Issues

- **Services not starting**: Check Docker logs with `docker compose logs`
- **SSL errors**: Verify certificate paths and permissions
- **502 Bad Gateway**: Check if backend services are running and healthy
- **Out of memory**: Monitor with `docker stats` and adjust container limits
- **Disk space**: Check with `df -h` and clean up old Docker images/containers

## 📚 Documentation

### Detailed Service Documentation

For comprehensive documentation on each service:

- **[Transcription Service README](src/nebula/transcript/README.md)**
  - Detailed FIFO queue architecture
  - Two-phase pipeline explanation
  - Audio chunking strategy
  - Slide detection algorithm
  - Performance characteristics
  - Troubleshooting guide
  - API examples

### Key Concepts

#### FIFO Queue System

The transcription service uses a First-In-First-Out queue to ensure ordered processing of video transcription jobs. This prevents resource contention during heavy operations (video download, audio extraction) while still allowing parallel processing of lighter tasks (slide detection).

#### Two-Phase Pipeline

- **Heavy Pipeline**: Sequential processing of resource-intensive operations (one job at a time)
- **Light Pipeline**: Parallel processing of independent operations (multiple jobs concurrently)

This separation optimizes both resource usage and throughput.

#### Intelligent Slide Detection

Uses GPT-4o Vision to detect slide numbers from video frames:

1. Extracts frames at transcript segment timestamps
2. Crops to the slide number region (bottom 5% of frame)
3. Sends to GPT-4o Vision with optimized prompts
4. Aligns detected numbers with transcript segments

### Example Transcription Output

```json
{
  "status": "done",
  "lectureUnitId": 456,
  "language": "en",
  "segments": [
    {
      "startTime": 0.0,
      "endTime": 5.2,
      "text": "Welcome to today's lecture on system design.",
      "slideNumber": 1
    },
    {
      "startTime": 5.2,
      "endTime": 10.8,
      "text": "We'll cover microservices architecture patterns.",
      "slideNumber": 2
    },
    {
      "startTime": 10.8,
      "endTime": 18.5,
      "text": "Let's start with the API gateway pattern and how it centralizes authentication.",
      "slideNumber": 3
    }
  ]
}
```

### Configuration Files

- **`llm_config.yml`**: AI service provider configuration (Azure OpenAI, OpenAI)
- **`nginx.local.conf`**: Local development nginx configuration
- **`nginx.production.conf`**: Production nginx configuration with SSL
- **`.env`**: Environment-specific settings (production)

### Performance Metrics

For a typical 1-hour lecture video:

- **Total Processing Time**: 10-20 minutes
- **Video Download**: 2-5 minutes
- **Audio Extraction**: 20-30 seconds
- **Whisper Transcription**: 5-10 minutes
- **Slide Detection**: 2-3 minutes

### API Usage Examples

#### Submit Job

```bash
curl -X POST http://localhost:3007/transcribe/start \
  -H "Authorization: nebula-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "videoUrl": "https://live.rbg.tum.de/w/test/12345.m3u8",
    "lectureUnitId": 456
  }'
```

#### Check Status

```bash
curl -H "Authorization: nebula-secret" \
  http://localhost:3007/transcribe/status/550e8400-e29b-41d4-a716-446655440000
```

#### Health Check

```bash
curl http://localhost:3007/health
```

## 🤝 Contributing

### Development Guidelines

1. **Code Style**: Follow PEP 8 for Python code
2. **Type Hints**: Use type annotations for all functions
3. **Documentation**: Update READMEs when adding features
4. **Testing**: Test locally before committing
5. **Logging**: Use appropriate log levels (DEBUG, INFO, WARNING, ERROR)

### Adding New Features

When adding new features to the transcription service:

1. Consider impact on FIFO queue processing
2. Maintain separation between heavy and light pipeline phases
3. Update both service README and main README
4. Test with various video formats and lengths
5. Verify cleanup of temporary files

## 📄 License

See the [LICENSE](../LICENSE) file in the root of the repository.

## 📞 Support

For issues, questions, or contributions:

- Check the troubleshooting sections above
- Review the detailed service documentation
- Consult the system design document for architectural insights
