# Weaviate RBAC Setup for Edutelligence

This directory contains scripts for setting up Role-Based A### Iris Service Connection
### Athena Service Connection
```python
import weaviate

# Connect as Athena service
client = weaviate.connect_to_local(
    host='localhost',
    port=8080,
    auth_credentials=weaviate.auth.AuthApiKey('<ATHENA_API_KEY>')
)

# Athena can access: any collections starting with "athena_"
collection = client.collections.get("athena_submissions")
```rt weaviate

# Connect as Iris service
client = weaviate.connect_to_local(
    host='localhost',
    port=8080,
    auth_credentials=weaviate.auth.AuthApiKey('<IRIS_API_KEY>')
)

# Iris can access: any collections starting with "iris_"
collection = client.collections.get("iris_faqs")
```(RBAC) for Weaviate in the Edutelligence platform. This setup ensures that each microservice (Atlas, Iris, and Athena) can only access and manage collections with their designated prefix while sharing a single Weaviate instance.

## Overview

The RBAC setup provides:
- **Prefix-based isolation**: Each microservice can only access collections starting with their prefix
- **Dynamic collection creation**: Services can create new collections without RBAC updates
- **Secure authentication**: Each service uses API key authentication
- **Granular permissions**: Services can create, read, update, and delete only their own data
- **Shared infrastructure**: All services use the same Weaviate instance

### Why Email Format for Usernames?

Weaviate's RBAC system requires usernames in email format for consistency with enterprise authentication systems. The service accounts use a pattern like `service-name@edutelligence.local` to clearly identify them as internal service accounts rather than real email addresses.

## Collection Access Strategy

Each microservice has access to collections based on **naming prefixes**:

| Microservice | Collection Prefix | Examples |
|--------------|-------------------|----------|
| **Atlas** | `atlas_*` | `atlas_exercises`, `atlas_competencies`, `atlas_clusters` |
| **Iris** | `iris_*` | `iris_faqs`, `iris_lectures`, `iris_buildlogs` |
| **Athena** | `athena_*` | `athena_submissions`, `athena_feedback`, `athena_assessments` |

This prefix-based approach allows:
- **Dynamic collection creation** - Services can create new collections as needed
- **Clear ownership** - Collection names immediately identify the owning service  
- **Simplified permissions** - Wildcard permissions cover all current and future collections
- **Easy scaling** - No need to update RBAC when adding new collection types

## Prerequisites

1. **Weaviate with RBAC enabled**
   ```bash
   # Ensure RBAC is enabled in your Weaviate configuration
   AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'false'
   AUTHORIZATION_ADMINLIST_ENABLED: 'true'
   AUTHORIZATION_ADMINLIST_USERS: 'admin@example.com'
   ```

2. **Python dependencies**
   ```bash
   pip install weaviate-client
   ```

3. **Admin access** to the Weaviate instance

## Quick Setup

### 1. Complete Setup (Recommended)
```bash
# Run complete RBAC setup
python permissions.py --all
```

### 2. Step-by-step Setup
```bash
# Create roles for each microservice
python permissions.py --create-roles

# Create users for each microservice  
python permissions.py --create-users

# Assign roles to users
python permissions.py --assign-permissions

# Verify setup
python permissions.py --verify

# Generate connection configurations
python permissions.py --generate-configs
```

### 3. With Authentication
If your Weaviate instance requires admin authentication:
```bash
python permissions.py --all \
    --admin-username admin@example.com \
    --admin-password your_admin_password
```

### 4. Custom Host/Port
```bash
python permissions.py --all \
    --host your-weaviate-host \
    --port 8080
```

## Usage Examples

### Atlas Service Connection
```python
import weaviate

# Connect as Atlas service
# Note: Uses API key authentication (API key generated during user creation)
client = weaviate.connect_to_local(
    host='localhost',
    port=8080,
    auth_credentials=weaviate.auth.AuthApiKey('<ATLAS_API_KEY>')
)

# Atlas can access: any collections starting with "atlas_"
collection = client.collections.get("atlas_exercises")
```

### Iris Service Connection  
```python
import weaviate

# Connect as Iris service
client = weaviate.connect_to_local(
    host='localhost', 
    port=8080,
    auth_credentials=weaviate.AuthBearerToken('iris-service@edutelligence.local:iris_secure_password_2024')
)

# Iris can access: Faqs, LectureUnits, Lectures, LectureTranscriptions, LectureUnitSegments
collection = client.collections.get("Faqs")
```

### Athena Service Connection (Future)
```python
import weaviate

# Connect as Athena service  
client = weaviate.connect_to_local(
    host='localhost',
    port=8080, 
    auth_credentials=weaviate.AuthBearerToken('athena-service@edutelligence.local:athena_secure_password_2024')
)

# Athena can access: AthenaSubmissions, AthenaFeedback (when implemented)
collection = client.collections.get("AthenaSubmissions")
```

## Script Options

| Option | Description |
|--------|-------------|
| `--host` | Weaviate host (default: localhost) |
| `--port` | Weaviate port (default: 8080) |
| `--admin-username` | Admin username for authentication |
| `--admin-password` | Admin password for authentication |
| `--create-users` | Create microservice users |
| `--create-roles` | Create microservice roles |
| `--assign-permissions` | Assign roles to users |
| `--verify` | Verify current setup |
| `--list` | List current RBAC setup |
| `--generate-configs` | Generate connection configurations |
| `--all` | Perform all setup actions |

## Security Considerations

### 🔒 Default Passwords
The script uses default passwords for demonstration. **Change these in production!**

```python
# Default passwords (CHANGE THESE!)
MICROSERVICE_USERS = {
    "atlas": {"password": "atlas_secure_password_2024"},
    "iris": {"password": "iris_secure_password_2024"},  
    "athena": {"password": "athena_secure_password_2024"}
}
```

### 🔐 Production Setup
1. **Use environment variables** for passwords:
   ```bash
   export ATLAS_WEAVIATE_PASSWORD="your_secure_atlas_password"
   export IRIS_WEAVIATE_PASSWORD="your_secure_iris_password"
   export ATHENA_WEAVIATE_PASSWORD="your_secure_athena_password"
   ```

2. **Store credentials securely** (e.g., HashiCorp Vault, AWS Secrets Manager)

3. **Use TLS/SSL** for Weaviate connections in production

4. **Regular password rotation**

### 🛡️ Permission Model
Each microservice can:
- ✅ **Create, read, update, delete** data in their own collections
- ✅ **Manage collection schemas** for their collections  
- ✅ **Create backups** of their collections
- ✅ **Read cluster health** information
- ❌ **Access other services' collections**
- ❌ **Modify cluster-wide settings**
- ❌ **Access admin functions**

## Troubleshooting

### Connection Issues
```bash
# Test basic connectivity
python -c "import weaviate; print(weaviate.connect_to_local().is_ready())"
```

### RBAC Not Working
1. Ensure RBAC is enabled in Weaviate config
2. Verify admin credentials are correct
3. Check Weaviate logs for authorization errors

### Permission Denied
1. Verify user exists: `python permissions.py --list`
2. Check role assignments: `python permissions.py --verify`
3. Ensure collection names match exactly

### Reset RBAC
If you need to start over:
```bash
# Note: This requires admin access to delete users/roles
# Delete users and roles manually through Weaviate admin interface
# Then re-run setup
python permissions.py --all
```

## Adding New Collections

With the prefix-based approach, **no RBAC updates are required** when adding new collections! 

Simply create collections following the naming convention:

### Atlas Service
```python
# Any collection starting with "atlas_" is automatically accessible
atlas_client.collections.create("atlas_new_feature")
atlas_client.collections.create("atlas_user_profiles") 
atlas_client.collections.create("atlas_analytics")
```

### Iris Service  
```python
# Any collection starting with "iris_" is automatically accessible
iris_client.collections.create("iris_chat_history")
iris_client.collections.create("iris_notifications")
iris_client.collections.create("iris_settings")
```

### Athena Service
```python  
# Any collection starting with "athena_" is automatically accessible
athena_client.collections.create("athena_test_cases")
athena_client.collections.create("athena_reports")
athena_client.collections.create("athena_templates")
```

The wildcard permissions (`atlas_*`, `iris_*`, `athena_*`) automatically grant access to any new collections that follow the naming convention.

## Monitoring and Maintenance

### Regular Tasks
- Monitor Weaviate logs for unauthorized access attempts
- Rotate service passwords periodically  
- Review and audit collection access patterns
- Regularly rotate API keys
- Monitor collection naming conventions to ensure proper prefix usage

### Health Checks
```bash
# Verify RBAC setup is working
python permissions.py --verify

# List current users and roles
python permissions.py --list
```

## Support

For issues related to:
- **Weaviate RBAC**: Check [Weaviate documentation](https://weaviate.io/developers/weaviate/configuration/authorization)
- **Edutelligence setup**: Create an issue in the repository
- **Collection schemas**: Refer to individual microservice documentation

---

**⚠️ Important**: Always test RBAC changes in a development environment before applying to production!
