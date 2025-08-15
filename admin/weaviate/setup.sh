#!/bin/bash

# Weaviate RBAC Quick Setup Script for Edutelligence
# This script provides an easy way to set up Weaviate RBAC for all microservices

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
WEAVIATE_HOST="localhost"
WEAVIATE_PORT="8080"
ADMIN_USERNAME=""
ADMIN_PASSWORD=""
SETUP_TYPE="full"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to display help
show_help() {
    cat << EOF
Weaviate RBAC Setup Script for Edutelligence

USAGE:
    $0 [OPTIONS]

OPTIONS:
    -h, --help              Show this help message
    -H, --host HOST         Weaviate host (default: localhost)
    -p, --port PORT         Weaviate port (default: 8080)
    -u, --admin-user USER   Admin username for authentication
    -P, --admin-pass PASS   Admin password for authentication
    -t, --type TYPE         Setup type: full, users, roles, permissions, verify
    -y, --yes               Skip confirmation prompts

EXAMPLES:
    # Full setup with default settings
    $0

    # Setup with custom host and port
    $0 --host weaviate.example.com --port 8080

    # Setup with authentication
    $0 --admin-user admin@example.com --admin-pass mypassword

    # Only create users
    $0 --type users

    # Verify existing setup
    $0 --type verify

MICROSERVICES:
    - Atlas: Exercise, Competency, ClusterCenter collections
    - Iris: Faqs, LectureUnits, Lectures, LectureTranscriptions, LectureUnitSegments collections  
    - Athena: AthenaSubmissions, AthenaFeedback collections (reserved)

EOF
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is required but not installed"
        exit 1
    fi
    
    # Check if weaviate client is available
    if ! python3 -c "import weaviate" 2>/dev/null; then
        print_error "Weaviate Python client is not installed"
        print_status "Install with: pip install weaviate-client"
        exit 1
    fi
    
    # Check if permissions.py exists
    if [[ ! -f "permissions.py" ]]; then
        print_error "permissions.py not found in current directory"
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Function to test Weaviate connectivity
test_connectivity() {
    print_status "Testing Weaviate connectivity to ${WEAVIATE_HOST}:${WEAVIATE_PORT}..."
    
    if python3 -c "
import weaviate
try:
    client = weaviate.connect_to_local(host='${WEAVIATE_HOST}', port=${WEAVIATE_PORT})
    if client.is_ready():
        print('✅ Connection successful')
    else:
        print('❌ Weaviate not ready')
        exit(1)
    client.close()
except Exception as e:
    print(f'❌ Connection failed: {e}')
    exit(1)
" 2>/dev/null; then
        print_success "Weaviate connectivity test passed"
    else
        print_error "Cannot connect to Weaviate at ${WEAVIATE_HOST}:${WEAVIATE_PORT}"
        print_status "Please ensure Weaviate is running and accessible"
        exit 1
    fi
}

# Function to run RBAC setup
run_rbac_setup() {
    local setup_args="--host ${WEAVIATE_HOST} --port ${WEAVIATE_PORT}"
    
    # Add authentication if provided
    if [[ -n "${ADMIN_USERNAME}" && -n "${ADMIN_PASSWORD}" ]]; then
        setup_args+=" --admin-username ${ADMIN_USERNAME} --admin-password ${ADMIN_PASSWORD}"
    fi
    
    case "${SETUP_TYPE}" in
        "full")
            print_status "Running full RBAC setup..."
            python3 permissions.py ${setup_args} --all
            ;;
        "users")
            print_status "Creating microservice users..."
            python3 permissions.py ${setup_args} --create-users
            ;;
        "roles")
            print_status "Creating microservice roles..."
            python3 permissions.py ${setup_args} --create-roles
            ;;
        "permissions")
            print_status "Assigning permissions..."
            python3 permissions.py ${setup_args} --assign-permissions
            ;;
        "verify")
            print_status "Verifying RBAC setup..."
            python3 permissions.py ${setup_args} --verify --list
            ;;
        *)
            print_error "Invalid setup type: ${SETUP_TYPE}"
            print_status "Valid types: full, users, roles, permissions, verify"
            exit 1
            ;;
    esac
}

# Function to display post-setup information
show_post_setup_info() {
    print_success "RBAC setup completed!"
    
    echo
    print_status "Next steps:"
    echo "1. Update your microservice configurations with the new credentials"
    echo "2. Test connections from each microservice"
    echo "3. Change default passwords in production environments"
    echo
    
    print_status "Generate connection configurations:"
    echo "python3 permissions.py --host ${WEAVIATE_HOST} --port ${WEAVIATE_PORT} --generate-configs"
    echo
    
    print_warning "Security reminder:"
    echo "- Default passwords are used for demonstration"
    echo "- Change passwords in production environments"
    echo "- Store credentials securely (environment variables, secrets manager)"
    echo
}

# Function to confirm setup
confirm_setup() {
    echo
    print_status "Setup Configuration:"
    echo "  Weaviate Host: ${WEAVIATE_HOST}"
    echo "  Weaviate Port: ${WEAVIATE_PORT}"
    echo "  Setup Type: ${SETUP_TYPE}"
    echo "  Authentication: $(if [[ -n "${ADMIN_USERNAME}" ]]; then echo "Yes (${ADMIN_USERNAME})"; else echo "No"; fi)"
    echo
    
    if [[ "${SKIP_CONFIRMATION}" != "true" ]]; then
        read -p "Proceed with RBAC setup? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Setup cancelled"
            exit 0
        fi
    fi
}

# Parse command line arguments
SKIP_CONFIRMATION=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -H|--host)
            WEAVIATE_HOST="$2"
            shift 2
            ;;
        -p|--port)
            WEAVIATE_PORT="$2"
            shift 2
            ;;
        -u|--admin-user)
            ADMIN_USERNAME="$2"
            shift 2
            ;;
        -P|--admin-pass)
            ADMIN_PASSWORD="$2"
            shift 2
            ;;
        -t|--type)
            SETUP_TYPE="$2"
            shift 2
            ;;
        -y|--yes)
            SKIP_CONFIRMATION=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Main execution
main() {
    echo "=========================================="
    echo "Weaviate RBAC Setup for Edutelligence"
    echo "=========================================="
    echo
    
    check_prerequisites
    test_connectivity
    confirm_setup
    
    echo
    print_status "Starting RBAC setup..."
    run_rbac_setup
    
    echo
    show_post_setup_info
}

# Run main function
main
