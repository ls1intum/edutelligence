#!/usr/bin/env python3
"""
Environment-based Weaviate RBAC Setup

This script reads configuration from environment variables and sets up RBAC accordingly.
This is useful for production deployments where credentials are managed via environment variables.

Usage:
    # With .env file
    python env_setup.py
    
    # With environment variables set
    export WEAVIATE_HOST=localhost
    export ATLAS_WEAVIATE_PASSWORD=secure_password
    python env_setup.py

Environment Variables:
    WEAVIATE_HOST - Weaviate host (default: localhost)
    WEAVIATE_PORT - Weaviate port (default: 8080)
    WEAVIATE_ADMIN_USERNAME - Admin username
    WEAVIATE_ADMIN_PASSWORD - Admin password
    ATLAS_WEAVIATE_USERNAME - Atlas service username
    ATLAS_WEAVIATE_PASSWORD - Atlas service password
    IRIS_WEAVIATE_USERNAME - Iris service username
    IRIS_WEAVIATE_PASSWORD - Iris service password
    ATHENA_WEAVIATE_USERNAME - Athena service username
    ATHENA_WEAVIATE_PASSWORD - Athena service password
"""

import os
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from permissions import WeaviateRBACManager, MICROSERVICE_COLLECTIONS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_environment_config() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    # Try to load .env file if it exists
    if os.path.exists('.env'):
        load_dotenv('.env')
        logger.info("📄 Loaded configuration from .env file")
    
    # Weaviate connection settings
    config = {
        'host': os.getenv('WEAVIATE_HOST', 'localhost'),
        'port': int(os.getenv('WEAVIATE_PORT', 8080)),
        'admin_username': os.getenv('WEAVIATE_ADMIN_USERNAME'),
        'admin_password': os.getenv('WEAVIATE_ADMIN_PASSWORD'),
    }
    
    # Microservice user configurations
    config['users'] = {
        'atlas': {
            'username': os.getenv('ATLAS_WEAVIATE_USERNAME', 'atlas-service@edutelligence.local'),
            'password': os.getenv('ATLAS_WEAVIATE_PASSWORD'),
        },
        'iris': {
            'username': os.getenv('IRIS_WEAVIATE_USERNAME', 'iris-service@edutelligence.local'),
            'password': os.getenv('IRIS_WEAVIATE_PASSWORD'),
        },
        'athena': {
            'username': os.getenv('ATHENA_WEAVIATE_USERNAME', 'athena-service@edutelligence.local'),
            'password': os.getenv('ATHENA_WEAVIATE_PASSWORD'),
        }
    }
    
    return config


def validate_config(config: Dict[str, Any]) -> bool:
    """Validate that required configuration is present."""
    logger.info("🔍 Validating configuration...")
    
    errors = []
    
    # Check for required passwords
    for service, user_config in config['users'].items():
        if not user_config['password']:
            errors.append(f"Missing password for {service} service ({service.upper()}_WEAVIATE_PASSWORD)")
    
    # Warn about default credentials
    warnings = []
    for service, user_config in config['users'].items():
        if user_config['password'] and 'change_me' in user_config['password']:
            warnings.append(f"Using default password for {service} service")
    
    # Report errors
    if errors:
        logger.error("❌ Configuration validation failed:")
        for error in errors:
            logger.error(f"   - {error}")
        return False
    
    # Report warnings
    if warnings:
        logger.warning("⚠️  Configuration warnings:")
        for warning in warnings:
            logger.warning(f"   - {warning}")
    
    logger.info("✅ Configuration validation passed")
    return True


def setup_rbac_from_env():
    """Set up RBAC using environment configuration."""
    logger.info("🚀 Starting environment-based RBAC setup...")
    
    # Load configuration
    config = load_environment_config()
    
    # Validate configuration
    if not validate_config(config):
        logger.error("💥 Configuration validation failed. Please check your environment variables.")
        return False
    
    # Display configuration (without passwords)
    logger.info("📋 Configuration:")
    logger.info(f"   Weaviate: {config['host']}:{config['port']}")
    logger.info(f"   Admin: {config['admin_username'] or 'Not specified'}")
    for service, user_config in config['users'].items():
        logger.info(f"   {service.capitalize()}: {user_config['username']}")
    
    # Initialize RBAC manager
    try:
        manager = WeaviateRBACManager(
            host=config['host'],
            port=config['port'],
            username=config['admin_username'],
            password=config['admin_password']
        )
    except Exception as e:
        logger.error(f"❌ Failed to connect to Weaviate: {e}")
        return False
    
    try:
        # Update the global user configuration with environment values
        from permissions import MICROSERVICE_USERS
        for service, user_config in config['users'].items():
            if service in MICROSERVICE_USERS:
                MICROSERVICE_USERS[service].update(user_config)
        
        # Perform RBAC setup
        logger.info("🔧 Creating roles...")
        manager.create_microservice_roles()
        
        logger.info("👥 Creating users...")
        manager.create_microservice_users()
        
        logger.info("🔗 Assigning permissions...")
        manager.assign_roles_to_users()
        
        logger.info("🔍 Verifying setup...")
        manager.verify_permissions()
        
        logger.info("📋 Listing current setup...")
        manager.list_current_setup()
        
        logger.info("📝 Generating connection configurations...")
        manager.generate_connection_configs()
        
        logger.info("🎉 RBAC setup completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"💥 RBAC setup failed: {e}")
        return False
    
    finally:
        manager.close()


def generate_env_template():
    """Generate a .env template file."""
    template_content = '''# Weaviate RBAC Environment Configuration
# Copy this file to .env and update with your actual credentials

# Weaviate connection settings
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8080

# Admin credentials (for RBAC setup)
WEAVIATE_ADMIN_USERNAME=admin@edutelligence.local
WEAVIATE_ADMIN_PASSWORD=change_me_admin_password_2024

# Atlas microservice credentials
ATLAS_WEAVIATE_USERNAME=atlas-service@edutelligence.local
ATLAS_WEAVIATE_PASSWORD=change_me_atlas_password_2024

# Iris microservice credentials  
IRIS_WEAVIATE_USERNAME=iris-service@edutelligence.local
IRIS_WEAVIATE_PASSWORD=change_me_iris_password_2024

# Athena microservice credentials
ATHENA_WEAVIATE_USERNAME=athena-service@edutelligence.local
ATHENA_WEAVIATE_PASSWORD=change_me_athena_password_2024

# Security notes:
# - Change all default passwords!
# - Use strong, unique passwords for each service
# - Consider using a secrets management system in production
'''
    
    with open('.env.template', 'w') as f:
        f.write(template_content)
    
    logger.info("📄 Generated .env.template file")
    logger.info("   Copy to .env and update with your credentials")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Environment-based Weaviate RBAC setup")
    parser.add_argument('--generate-template', action='store_true', 
                       help='Generate .env template file')
    parser.add_argument('--check-config', action='store_true',
                       help='Check configuration without setting up RBAC')
    
    args = parser.parse_args()
    
    if args.generate_template:
        generate_env_template()
        return
    
    if args.check_config:
        config = load_environment_config()
        validate_config(config)
        return
    
    # Run RBAC setup
    success = setup_rbac_from_env()
    if not success:
        exit(1)


if __name__ == '__main__':
    main()
