#!/usr/bin/env python3
"""
Weaviate RBAC Setup for Ed# User configurations for each microservice (email format required by Weaviate)
MICROSERVICE_USERS = {
    "atlas": {
        "username": "atlas-service@edutelligence.local",
        "description": "Atlas microservice - Exercise and competency management"
    },
    "iris": {
        "username": "iris-service@edutelligence.local", 
        "description": "Iris microservice - FAQ and lecture unit management"
    },
    "athena": {
        "username": "athena-service@edutelligence.local",
        "description": "Athena microservice - Assessment and programming analysis"
    }
}roservices

This script sets up Role-Based Access Control (RBAC) for Weaviate to allow
each microservice (Atlas, Iris, Athena) to manage their own collections
on a shared Weaviate instance while preventing interference with other services.

Usage:
    python permissions.py --host localhost --port 8080 --create-users --create-roles --assign-permissions

Requirements:
    - Weaviate instance with RBAC enabled
    - Admin credentials for initial setup
"""

import argparse
import logging
import sys
from typing import List, Dict, Any
import weaviate


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Collection prefix mappings for each microservice
# Each service can access collections that start with their prefix
MICROSERVICE_PREFIXES = {
    "atlas": "atlas_",
    "iris": "iris_", 
    "athena": "athena_"
}# User configurations for each microservice
# Note: Weaviate RBAC requires email format for usernames, but these are service accounts
MICROSERVICE_USERS = {
    "atlas": {
        "username": "atlas-service@edutelligence.local",
        "password": "atlas_secure_password_2024",  # Should be changed in production
    },
    "iris": {
        "username": "iris-service@edutelligence.local", 
        "password": "iris_secure_password_2024",   # Should be changed in production
    },
    "athena": {
        "username": "athena-service@edutelligence.local",
        "password": "athena_secure_password_2024", # Should be changed in production  
    }
}


class WeaviateRBACManager:
    """Manages RBAC setup for Weaviate instance."""
    
    def __init__(self, host: str = "localhost", port: int = 8080, username: str = None, password: str = None):
        """Initialize Weaviate client with admin credentials."""
        try:
            if username and password:
                # Connect with authentication
                self.client = weaviate.connect_to_local(
                    host=host,
                    port=port,
                    auth_credentials=weaviate.auth.AuthApiKey(password)  # Use API key auth
                )
            else:
                # Connect without authentication (for initial setup)
                self.client = weaviate.connect_to_local(host=host, port=port)
                
            logger.info(f"✅ Connected to Weaviate at {host}:{port}")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Weaviate: {e}")
            raise
    
    def close(self):
        """Close the Weaviate client connection."""
        if self.client:
            self.client.close()
            logger.info("🔌 Disconnected from Weaviate")
    
    def create_microservice_roles(self):
        """Create roles for each microservice with appropriate permissions."""
        logger.info("🔧 Creating microservice roles...")
        
        for service_name, collection_prefix in MICROSERVICE_PREFIXES.items():
            role_name = f"{service_name}_role"
            
            try:
                # Create permissions for this microservice's collection prefix
                # Using wildcard pattern to match all collections with the prefix
                permissions = [
                    # Data operations - wildcard access to all collections with prefix
                    {
                        "action": "data",
                        "collections": {"collection": f"{collection_prefix}*"},
                        "create": True,
                        "read": True, 
                        "update": True,
                        "delete": True
                    },
                    # Collection management - wildcard access
                    {
                        "action": "collections",
                        "collections": {"collection": f"{collection_prefix}*"},
                        "create_collection": True,
                        "read_config": True,
                        "update_config": True,
                        "delete_collection": True
                    },
                    # Backup permissions for own collections
                    {
                        "action": "backup",
                        "collections": {"collection": f"{collection_prefix}*"},
                        "manage": True
                    },
                    # Cluster-level read permissions (for health checks, etc.)
                    {
                        "action": "cluster",
                        "read": True
                    }
                ]
                
                # Create the role
                self.client.roles.create(
                    role_name=role_name,
                    permissions=permissions
                )
                
                logger.info(f"✅ Created role '{role_name}' with wildcard permissions for collections: {collection_prefix}*")
                
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.warning(f"⚠️  Role '{role_name}' already exists, skipping creation")
                else:
                    logger.error(f"❌ Failed to create role '{role_name}': {e}")
                    raise
    
    def create_microservice_users(self):
        """Create users for each microservice."""
        logger.info("👥 Creating microservice users...")
        
        for service_name, user_config in MICROSERVICE_USERS.items():
            try:
                # Create database user
                api_key = self.client.users.db.create(user_id=user_config["username"])
                logger.info(f"✅ Created user '{user_config['username']}' for {service_name}")
                logger.info(f"   Generated API key: {api_key} (store this securely!)")
                
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.warning(f"⚠️  User '{user_config['username']}' already exists, skipping creation")
                else:
                    logger.error(f"❌ Failed to create user '{user_config['username']}': {e}")
                    raise
    
    def assign_roles_to_users(self):
        """Assign appropriate roles to microservice users."""
        logger.info("🔗 Assigning roles to users...")
        
        for service_name, user_config in MICROSERVICE_USERS.items():
            role_name = f"{service_name}_role"
            username = user_config["username"]
            
            try:
                self.client.users.db.assign_roles(
                    user_id=username,
                    role_names=[role_name]
                )
                
                logger.info(f"✅ Assigned role '{role_name}' to user '{username}'")
                
            except Exception as e:
                if "already assigned" in str(e).lower():
                    logger.warning(f"⚠️  Role '{role_name}' already assigned to '{username}', skipping")
                else:
                    logger.error(f"❌ Failed to assign role '{role_name}' to user '{username}': {e}")
                    raise
    
    def list_current_setup(self):
        """List current RBAC setup for verification."""
        logger.info("📋 Current RBAC Setup:")
        
        try:
            # List roles
            roles = self.client.roles.list_all()
            logger.info(f"📝 Roles ({len(roles)}):")
            for role in roles:
                if any(service in role for service in MICROSERVICE_PREFIXES.keys()):
                    logger.info(f"   - {role}")
            
            # List users  
            users = self.client.users.db.list_all()
            logger.info(f"👤 Users ({len(users)}):")
            for user in users:
                if any(service in user for service in MICROSERVICE_PREFIXES.keys()):
                    logger.info(f"   - {user}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to list current setup: {e}")
    
    def verify_permissions(self):
        """Verify that permissions are correctly set up."""
        logger.info("🔍 Verifying permissions setup...")
        
        try:
            # Get all roles and users
            all_roles = self.client.roles.list_all()
            all_users = self.client.users.db.list_all()
            
            for service_name in MICROSERVICE_PREFIXES.keys():
                role_name = f"{service_name}_role"
                username = MICROSERVICE_USERS[service_name]["username"]
                
                # Check if role exists
                if role_name in all_roles:
                    logger.info(f"✅ {service_name.upper()}: Role '{role_name}' exists")
                else:
                    logger.error(f"❌ {service_name.upper()}: Role '{role_name}' missing")
                    continue
                
                # Check if user exists
                if username in all_users:
                    logger.info(f"✅ {service_name.upper()}: User '{username}' exists")
                else:
                    logger.error(f"❌ {service_name.upper()}: User '{username}' missing")
                    continue
                
                # Check role assignment
                try:
                    user_roles = self.client.users.db.get_roles(user_id=username)
                    if role_name in user_roles:
                        logger.info(f"✅ {service_name.upper()}: Role properly assigned")
                    else:
                        logger.error(f"❌ {service_name.upper()}: Role not assigned to user")
                except Exception as e:
                    logger.error(f"❌ {service_name.upper()}: Cannot verify role assignment - {e}")
                    
        except Exception as e:
            logger.error(f"❌ Verification failed: {e}")
    
    def generate_connection_configs(self):
        """Generate connection configuration examples for each microservice."""
        logger.info("📝 Generating connection configurations...")
        
        print("\n" + "="*80)
        print("MICROSERVICE CONNECTION CONFIGURATIONS")
        print("="*80)
        
        for service_name, user_config in MICROSERVICE_USERS.items():
            collection_prefix = MICROSERVICE_PREFIXES[service_name]
            
            print(f"\n🔧 {service_name.upper()} Service Configuration:")
            print(f"   Username: {user_config['username']}")
            print(f"   Collection Prefix: {collection_prefix}* (all collections starting with '{collection_prefix}')")
            print(f"   Example Python connection:")
            print(f"   ```python")
            print(f"   import weaviate")
            print(f"   from weaviate.auth import Auth")
            print(f"   ")
            print(f"   client = weaviate.connect_to_local(")
            print(f"       host='localhost',")
            print(f"       port=8080,")
            print(f"       auth_credentials=Auth.api_key('<API_KEY_FOR_{service_name.upper()}>')")
            print(f"   )")
            print(f"   ")
            print(f"   # {service_name.capitalize()} can access any collection starting with '{collection_prefix}'")
            print(f"   # Examples: {collection_prefix}exercises, {collection_prefix}users, {collection_prefix}data, etc.")
            print(f"   collection = client.collections.get('{collection_prefix}example')")
            print(f"   ```")
        
        print(f"\n⚠️  SECURITY NOTES:")
        print(f"   - API keys are generated when users are created")
        print(f"   - Store API keys securely (environment variables, secrets manager)")
        print(f"   - Each service can only access collections with their prefix")
        print(f"   - Services cannot access collections belonging to other services")
        print(f"   - Wildcard permissions allow dynamic collection creation within service scope")
        print("="*80)


def main():
    """Main function to set up Weaviate RBAC."""
    parser = argparse.ArgumentParser(description="Setup Weaviate RBAC for Edutelligence microservices")
    parser.add_argument("--host", default="localhost", help="Weaviate host (default: localhost)")
    parser.add_argument("--port", type=int, default=8080, help="Weaviate port (default: 8080)")
    parser.add_argument("--admin-username", help="Admin username for authentication")
    parser.add_argument("--admin-password", help="Admin password for authentication")
    parser.add_argument("--create-users", action="store_true", help="Create microservice users")
    parser.add_argument("--create-roles", action="store_true", help="Create microservice roles")
    parser.add_argument("--assign-permissions", action="store_true", help="Assign roles to users")
    parser.add_argument("--verify", action="store_true", help="Verify current setup")
    parser.add_argument("--list", action="store_true", help="List current RBAC setup")
    parser.add_argument("--generate-configs", action="store_true", help="Generate connection configs")
    parser.add_argument("--all", action="store_true", help="Perform all setup actions")
    
    args = parser.parse_args()
    
    if not any([args.create_users, args.create_roles, args.assign_permissions, 
                args.verify, args.list, args.generate_configs, args.all]):
        parser.print_help()
        return
    
    # Initialize RBAC manager
    manager = WeaviateRBACManager(
        host=args.host,
        port=args.port,
        username=args.admin_username,
        password=args.admin_password
    )
    
    try:
        if args.all:
            # Perform all setup actions
            manager.create_microservice_roles()
            manager.create_microservice_users()
            manager.assign_roles_to_users()
            manager.verify_permissions()
            manager.list_current_setup()
            manager.generate_connection_configs()
        else:
            # Perform individual actions
            if args.create_roles:
                manager.create_microservice_roles()
            
            if args.create_users:
                manager.create_microservice_users()
            
            if args.assign_permissions:
                manager.assign_roles_to_users()
            
            if args.verify:
                manager.verify_permissions()
            
            if args.list:
                manager.list_current_setup()
            
            if args.generate_configs:
                manager.generate_connection_configs()
        
        logger.info("🎉 RBAC setup completed successfully!")
        
    except Exception as e:
        logger.error(f"💥 Setup failed: {e}")
        sys.exit(1)
    
    finally:
        manager.close()


if __name__ == "__main__":
    main()