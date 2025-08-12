# Edutelligence Admin Scripts

This directory contains administrative scripts and configurations for setting up and managing the Edutelligence platform infrastructure.

## Directory Structure

```
admin/
├── weaviate/          # Weaviate RBAC setup and management
│   ├── README.md      # Detailed Weaviate RBAC documentation
│   ├── permissions.py # Main RBAC setup script
│   ├── env_setup.py   # Environment-based setup script
│   ├── setup.sh       # Quick setup bash script
│   ├── connection_examples.py # Example connection scripts
│   ├── docker-compose.yml     # Weaviate with RBAC enabled
│   ├── .env.example   # Environment variables template
│   └── requirements.txt       # Python dependencies
└── README.md          # This file
```

## Services

### Weaviate RBAC Setup

Sets up Role-Based Access Control for Weaviate to allow each microservice (Atlas, Iris, Athena) to manage collections with their designated prefix while sharing a single Weaviate instance.

**Quick Start:**
```bash
cd admin/weaviate
pip install -r requirements.txt
python permissions.py --all
```

**Features:**
- Individual user accounts for each microservice
- Prefix-based collection access with wildcard permissions
- Dynamic collection creation without RBAC updates
- Secure isolation between services
- Docker Compose configuration
- Environment-based configuration

**Collection Access by Service:**
- **Atlas**: All collections starting with `atlas_*` (e.g., `atlas_exercises`, `atlas_competencies`)
- **Iris**: All collections starting with `iris_*` (e.g., `iris_faqs`, `iris_lectures`)
- **Athena**: All collections starting with `athena_*` (e.g., `athena_submissions`, `athena_feedback`)


## Usage Scenarios

### Development Setup
For local development with default settings:
```bash
cd admin/weaviate
./setup.sh --type full
```

### Production Setup
For production with environment variables:
```bash
cd admin/weaviate
cp .env.example .env
# Edit .env with your credentials
python env_setup.py
```

### Testing Connections
Test microservice connections:
```bash
cd admin/weaviate
python connection_examples.py --service atlas --all-tests
python connection_examples.py --service iris --test-connection
```

## Security Considerations

1. **Store API keys securely** in production (use secrets manager)
2. **Use environment variables** for credentials
3. **Enable TLS/SSL** for Weaviate in production
4. **Regular API key rotation**
5. **Monitor access logs** for unauthorized attempts
6. **Follow collection naming conventions** to ensure proper access control

## Prerequisites

- Python 3.8+
- Docker and Docker Compose (for Weaviate)
- Network access to Weaviate instance