"""
Module for building the Java gRPC client for Hyperion.
This script copies the proto file to the Java client project and builds the library.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def extract_gradle_property(gradle_file, property_name):
    """
    Extract a property value from a Gradle build file.
    
    Args:
        gradle_file: Path to the Gradle build file
        property_name: Name of the property to extract
        
    Returns:
        The value of the property or None if not found
    """
    with open(gradle_file, 'r') as f:
        content = f.read()
        
    # Match pattern like: group = 'de.tum.cit.aet'
    pattern = rf"{property_name}\s*=\s*'([^']+)'"
    match = re.search(pattern, content)
    
    if match:
        return match.group(1)
    return None


def extract_project_name(settings_gradle):
    """
    Extract the project name from settings.gradle.
    
    Args:
        settings_gradle: Path to the settings.gradle file
        
    Returns:
        The project name or None if not found
    """
    with open(settings_gradle, 'r') as f:
        content = f.read()
        
    # Match pattern like: rootProject.name = 'hyperion'
    pattern = r"rootProject\.name\s*=\s*'([^']+)'"
    match = re.search(pattern, content)
    
    if match:
        return match.group(1)
    return None


def main():
    """
    Copies the Hyperion proto file to the Java client project and builds the library.
    The built library is published to the local Maven repository for use in Artemis.
    """
    # Determine directories
    script_dir = Path(__file__).parent.absolute()
    hyperion_dir = script_dir.parents[1]  # Two levels up from this file
    java_client_dir = hyperion_dir / "java-client"
    
    # Locate proto file
    proto_src = hyperion_dir / "app" / "protos" / "hyperion.proto"
    proto_dest = java_client_dir / "proto" / "hyperion.proto"
    
    if not proto_src.exists():
        print(f"Error: Source proto file not found at {proto_src}")
        return 1
    
    # Make sure target directory exists
    proto_dest.parent.mkdir(parents=True, exist_ok=True)
    
    # Copy the proto file
    shutil.copy2(proto_src, proto_dest)
    print(f"Proto file copied from {proto_src} to {proto_dest}")
    
    # Extract artifact information from build.gradle
    build_gradle = java_client_dir / "build.gradle"
    settings_gradle = java_client_dir / "settings.gradle"
    
    group_id = extract_gradle_property(build_gradle, "group")
    version = extract_gradle_property(build_gradle, "version")
    artifact_id = extract_project_name(settings_gradle)
    
    if not group_id or not version or not artifact_id:
        print("Warning: Could not extract all properties from Gradle files")
        group_id = group_id or "de.tum.cit.aet"
        version = version or "0.1.0-SNAPSHOT"
        artifact_id = artifact_id or "hyperion"
    
    # Build the Java gRPC library
    print("Building Java gRPC client library...")
    try:
        # Change to the Java gRPC directory
        os.chdir(java_client_dir)
        
        # Run gradle build
        result = subprocess.run(
            ["./gradlew", "clean", "build", "publishToMavenLocal"],
            check=True,
            capture_output=True,
            text=True
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        print("\nJava gRPC client library built and published to Maven Local")
        print("You can now use it in Artemis with the dependency:")
        print(f"implementation '{group_id}:{artifact_id}:{version}'")
        
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error building Java gRPC client library: {e}", file=sys.stderr)
        print(e.stdout)
        print(e.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
