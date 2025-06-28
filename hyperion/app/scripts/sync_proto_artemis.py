#!/usr/bin/env python3
"""
Simple Proto File Synchronization Script for Artemis Integration

This script synchronizes the Hyperion proto file with the Artemis project.
It maintains a simple configuration file to remember the Artemis path.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


# Configuration file name (will be gitignored)
CONFIG_FILE = ".artemis_sync_config.json"


def load_config() -> dict:
    """Load configuration from file."""
    config_path = Path(__file__).parent.parent.parent / CONFIG_FILE
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(config: dict) -> None:
    """Save configuration to file."""
    config_path = Path(__file__).parent.parent.parent / CONFIG_FILE
    try:
        config_path.write_text(json.dumps(config, indent=2))
    except OSError as e:
        print(f"⚠️  Warning: Could not save config: {e}")


def find_artemis_project() -> Optional[Path]:
    """Simple search for Artemis project."""
    # Start from current directory and look for Artemis
    current_dir = Path.cwd()

    # Common paths to check
    potential_paths = [
        # If we're in hyperion, look for artemis as sibling
        current_dir.parent / "Artemis",
        current_dir.parent / "artemis",
        # Check Documents folder
        Path.home() / "Documents" / "Artemis",
        Path.home() / "Documents" / "artemis",
    ]

    for path in potential_paths:
        if path.exists() and (path / "build.gradle").exists():
            return path

    return None


def get_artemis_path(config: dict, provided_path: Optional[str] = None) -> Path:
    """Get Artemis project path with user confirmation."""

    if provided_path:
        path = Path(provided_path).resolve()
        if not path.exists():
            print(f"❌ Provided path does not exist: {path}")
            sys.exit(1)
        if not (path / "build.gradle").exists():
            print(f"❌ Not an Artemis project (no build.gradle): {path}")
            sys.exit(1)
        return path

    # Check saved config
    saved_path = config.get("artemis_path")
    if saved_path:
        path = Path(saved_path)
        if path.exists() and (path / "build.gradle").exists():
            response = (
                input(f"🤔 Use saved Artemis path: {path}? [Y/n]: ").strip().lower()
            )
            if response in ("", "y", "yes"):
                return path

    # Try to find automatically
    auto_path = find_artemis_project()
    if auto_path:
        response = (
            input(f"🔍 Found Artemis project: {auto_path}. Use this? [Y/n]: ")
            .strip()
            .lower()
        )
        if response in ("", "y", "yes"):
            config["artemis_path"] = str(auto_path)
            save_config(config)
            return auto_path

    # Ask user for path
    while True:
        user_path = input("📂 Enter path to Artemis project: ").strip()
        if not user_path:
            print("❌ Path cannot be empty")
            continue

        path = Path(user_path).expanduser().resolve()
        if not path.exists():
            print(f"❌ Path does not exist: {path}")
            continue

        if not (path / "build.gradle").exists():
            print(f"❌ Not an Artemis project (no build.gradle): {path}")
            continue

        # Save the path
        config["artemis_path"] = str(path)
        save_config(config)
        return path


def sync_proto_file(
    source_path: Path, target_path: Path, dry_run: bool = False
) -> bool:
    """Synchronize the proto file."""

    print(f"📂 Source: {source_path}")
    print(f"📂 Target: {target_path}")

    if not source_path.exists():
        print(f"❌ Source proto file not found: {source_path}")
        return False

    if dry_run:
        print(f"🔍 DRY RUN: Would copy proto file to {target_path}")
        if target_path.exists():
            print("⚠️  Target file already exists and would be overwritten")
        return True

    try:
        # Create target directory if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file
        shutil.copy2(source_path, target_path)

        # Show success
        size = target_path.stat().st_size
        print(f"✅ Proto file synchronized successfully! ({size} bytes)")
        return True

    except Exception as e:
        print(f"❌ Error synchronizing proto file: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Synchronize Hyperion proto file with Artemis project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  poetry run sync-proto-artemis                        # Interactive mode
  poetry run sync-proto-artemis --artemis-path /path   # Specify path
  poetry run sync-proto-artemis --dry-run              # Preview changes
        """,
    )

    parser.add_argument("--artemis-path", type=str, help="Path to Artemis project root")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    print("🚀 Hyperion → Artemis Proto Synchronization")
    print("=" * 50)

    # Load configuration
    config = load_config()

    # Get source proto file (we know where this is)
    source_proto = Path(__file__).parent.parent / "protos" / "hyperion.proto"

    # Get Artemis path
    artemis_path = get_artemis_path(config, args.artemis_path)
    target_proto = artemis_path / "src" / "main" / "java" / "de" / "tum" / "cit" / "aet" / "artemis" / "hyperion" / "proto" / "hyperion.proto"

    # Perform synchronization
    success = sync_proto_file(source_proto, target_proto, args.dry_run)

    if success:
        if not args.dry_run:
            print()
            print("🎯 Next Steps:")
            print("1. Run './gradlew generateProto' in Artemis to generate stubs")
            print("2. Run './gradlew build' to compile everything")
            print()
            print("✅ Synchronization completed!")
        sys.exit(0)
    else:
        print("❌ Synchronization failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
