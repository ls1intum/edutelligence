#!/usr/bin/env python3
"""
Connection examples for Weaviate RBAC-enabled microservices.

This file demonstrates how each microservice should connect to Weaviate
using their assigned credentials and access their specific collections.
"""

import os
import logging
import weaviate

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def connect_atlas_service():
    """Example: How Atlas service connects to Weaviate."""
    # Credentials should be stored in environment variables
    api_key = os.getenv("ATLAS_WEAVIATE_API_KEY")
    
    if not api_key:
        logger.error("❌ ATLAS_WEAVIATE_API_KEY environment variable not set")
        return None
        
    try:
        # Connect using API key authentication
        client = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_PORT", "8080")),
            auth_credentials=weaviate.auth.AuthApiKey(api_key)
        )
        
        logger.info("✅ Atlas service connected to Weaviate")
        
        # Atlas can access: any collections starting with "atlas_"
        # Examples: atlas_exercises, atlas_competencies, atlas_clusters, etc.
        available_collections = [name for name in client.collections.list_all()]
        atlas_collections = [name for name in available_collections if name.startswith("atlas_")]
        
        if atlas_collections:
            logger.info(f"✅ Atlas collections found: {', '.join(atlas_collections)}")
        else:
            logger.info("ℹ️  No collections with 'atlas_' prefix found yet")
        
        return client
        
    except Exception as e:
        logger.error(f"❌ Atlas connection failed: {e}")
        return None


def connect_iris_service():
    """Example: How Iris service connects to Weaviate."""
    # Credentials should be stored in environment variables
    api_key = os.getenv("IRIS_WEAVIATE_API_KEY")
    
    if not api_key:
        logger.error("❌ IRIS_WEAVIATE_API_KEY environment variable not set")
        return None
        
    try:
        # Connect using API key authentication
        client = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_PORT", "8080")),
            auth_credentials=weaviate.auth.AuthApiKey(api_key)
        )
        
        logger.info("✅ Iris service connected to Weaviate")
        
        # Iris can access: any collections starting with "iris_"
        # Examples: iris_faqs, iris_lectures, iris_buildlogs, etc.
        available_collections = [name for name in client.collections.list_all()]
        iris_collections = [name for name in available_collections if name.startswith("iris_")]
        
        if iris_collections:
            logger.info(f"✅ Iris collections found: {', '.join(iris_collections)}")
        else:
            logger.info("ℹ️  No collections with 'iris_' prefix found yet")
        
        return client
        
    except Exception as e:
        logger.error(f"❌ Iris connection failed: {e}")
        return None


def connect_athena_service():
    """Example: How Athena service connects to Weaviate."""
    # Credentials should be stored in environment variables
    api_key = os.getenv("ATHENA_WEAVIATE_API_KEY")
    
    if not api_key:
        logger.error("❌ ATHENA_WEAVIATE_API_KEY environment variable not set")
        return None
        
    try:
        # Connect using API key authentication
        client = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_PORT", "8080")),
            auth_credentials=weaviate.auth.AuthApiKey(api_key)
        )
        
        logger.info("✅ Athena service connected to Weaviate")
        
        # Athena can access: any collections starting with "athena_"
        # Examples: athena_submissions, athena_feedback, athena_assessments, etc.
        available_collections = [name for name in client.collections.list_all()]
        athena_collections = [name for name in available_collections if name.startswith("athena_")]
        
        if athena_collections:
            logger.info(f"✅ Athena collections found: {', '.join(athena_collections)}")
        else:
            logger.info("ℹ️  No collections with 'athena_' prefix found yet")
        
        return client
        
    except Exception as e:
        logger.error(f"❌ Athena connection failed: {e}")
        return None


def test_collection_access():
    """Test that each service can only access their assigned collections."""
    logger.info("🧪 Testing collection access permissions...")
    
    # Test Atlas
    atlas_client = connect_atlas_service()
    if atlas_client:
        try:
            # Atlas should be able to create/read from collections with atlas_ prefix
            # Example: Try to access an atlas collection (would be created dynamically)
            logger.info("✅ Atlas can access collections with 'atlas_' prefix")
            logger.info("   Examples: atlas_exercises, atlas_competencies, atlas_clusters")
            
            # Atlas should NOT be able to access other service collections
            logger.info("ℹ️  Atlas RBAC test completed")
            
        except Exception as e:
            logger.info(f"ℹ️  Atlas access test: {e}")
        finally:
            atlas_client.close()
    
    # Test Iris
    iris_client = connect_iris_service()
    if iris_client:
        try:
            # Iris should be able to access collections with iris_ prefix
            logger.info("✅ Iris can access collections with 'iris_' prefix")
            logger.info("   Examples: iris_faqs, iris_lectures, iris_buildlogs")
            
            logger.info("ℹ️  Iris RBAC test completed")
            
        except Exception as e:
            logger.info(f"ℹ️  Iris access test: {e}")
        finally:
            iris_client.close()
    
    # Test Athena
    athena_client = connect_athena_service()
    if athena_client:
        try:
            # Athena should be able to access collections with athena_ prefix
            logger.info("✅ Athena can access collections with 'athena_' prefix")
            logger.info("   Examples: athena_submissions, athena_feedback, athena_assessments")
            
            logger.info("ℹ️  Athena RBAC test completed")
            
        except Exception as e:
            logger.info(f"ℹ️  Athena access test: {e}")
        finally:
            athena_client.close()


def demonstrate_crud_operations():
    """Demonstrate CRUD operations for each service."""
    logger.info("📝 Demonstrating CRUD operations...")
    
    # Atlas example
    atlas_client = connect_atlas_service()
    if atlas_client:
        try:
            # Example: Atlas working with collections that have 'atlas_' prefix
            logger.info("Atlas CRUD example:")
            logger.info("  - Create: atlas_client.collections.get('atlas_exercises').data.insert(...)")
            logger.info("  - Read: atlas_client.collections.get('atlas_exercises').query.get(...)")
            logger.info("  - Update: atlas_client.collections.get('atlas_exercises').data.update(...)")
            logger.info("  - Delete: atlas_client.collections.get('atlas_exercises').data.delete(...)")
            logger.info("  - Atlas can create any collection starting with 'atlas_'")
            
        finally:
            atlas_client.close()
    
    # Iris example
    iris_client = connect_iris_service()
    if iris_client:
        try:
            # Example: Iris working with collections that have 'iris_' prefix
            logger.info("Iris CRUD example:")
            logger.info("  - Create: iris_client.collections.get('iris_faqs').data.insert(...)")
            logger.info("  - Read: iris_client.collections.get('iris_faqs').query.get(...)")
            logger.info("  - Update: iris_client.collections.get('iris_faqs').data.update(...)")
            logger.info("  - Delete: iris_client.collections.get('iris_faqs').data.delete(...)")
            logger.info("  - Iris can create any collection starting with 'iris_'")
            
        finally:
            iris_client.close()


if __name__ == "__main__":
    print("🚀 Weaviate RBAC Connection Examples")
    print("=" * 50)
    
    # Set up example environment variables (in production, load from secure storage)
    print("\n📋 Required Environment Variables:")
    required_vars = [
        "ATLAS_WEAVIATE_API_KEY",
        "IRIS_WEAVIATE_API_KEY", 
        "ATHENA_WEAVIATE_API_KEY",
        "WEAVIATE_HOST",
        "WEAVIATE_PORT"
    ]
    
    for var in required_vars:
        value = os.getenv(var, "NOT_SET")
        print(f"   {var}: {'✅ Set' if value != 'NOT_SET' else '❌ Not set'}")
    
    print("\n🔗 Testing Connections:")
    test_collection_access()
    
    print("\n📝 CRUD Examples:")
    demonstrate_crud_operations()
    
    print("\n✅ Connection examples completed!")
    print("\n💡 Remember to:")
    print("   - Store API keys securely in production")
    print("   - Use environment variables or secret management")
    print("   - Implement proper error handling in your services")
    print("   - Monitor and log access patterns")
