#!/usr/bin/env python
"""
Generate gRPC stubs from proto files.

Usage:
    poetry run generate-grpc
"""
import logging
import subprocess
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("grpc-stub-generator")


def main():
    """Generate gRPC stubs from proto files."""
    # Get project root directory
    project_root = Path(__file__).parent.parent
    proto_dir = project_root / "protos"
    output_dir = project_root / "grpc"

    # Check if proto directory exists
    if not proto_dir.exists():
        logger.error(f"Proto directory not found at {proto_dir}")
        sys.exit(1)

    # Get all proto files
    proto_files = list(proto_dir.glob("*.proto"))
    if not proto_files:
        logger.error(f"No proto files found in {proto_dir}")
        sys.exit(1)

    logger.info(
        f"Found {len(proto_files)} proto file(s): {[p.name for p in proto_files]}"
    )

    # Generate Python code for each proto file
    for proto_file in proto_files:
        logger.info(f"Generating stubs for {proto_file.name}")

        # Build command
        cmd = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"--proto_path={proto_dir}",
            f"--python_out={output_dir}",
            f"--pyi_out={output_dir}",
            f"--grpc_python_out={output_dir}",
            str(proto_file),
        ]

        # Execute command
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Successfully generated stubs for {proto_file.name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error generating stubs for {proto_file.name}: {e}")
            logger.error(f"STDOUT: {e.stdout}")
            logger.error(f"STDERR: {e.stderr}")
            sys.exit(1)

    # Fix the import statements in the generated files
    logger.info("Fixing import statements in generated files...")
    for proto_file in proto_files:
        base_name = proto_file.stem
        grpc_file = output_dir / f"{base_name}_pb2_grpc.py"

        if grpc_file.exists():
            with open(grpc_file, "r") as f:
                content = f.read()

            # Fix the import statement to use relative import
            fixed_content = content.replace(
                f"import {base_name}_pb2 as {base_name}__pb2",
                f"from . import {base_name}_pb2 as {base_name}__pb2",
            )

            with open(grpc_file, "w") as f:
                f.write(fixed_content)

            logger.info(f"Fixed import statements in {grpc_file.name}")

    logger.info("Stub generation complete!")


if __name__ == "__main__":
    main()
