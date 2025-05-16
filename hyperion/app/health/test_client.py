#!/usr/bin/env python
"""
Simple client to test the Health service of the gRPC server.

Usage:
    poetry run python -m app.health.test_client
"""

import sys
import grpc
import time
from app.grpc import hyperion_pb2, hyperion_pb2_grpc
from app.settings import settings


def main():
    """Test the Health service by sending a Ping request."""
    # Create a gRPC channel
    address = f"{settings.GRPC_HOST}:{settings.GRPC_PORT}"
    print(f"Connecting to gRPC server at {address}...")

    with grpc.insecure_channel(address) as channel:
        try:
            # Create a stub (client)
            stub = hyperion_pb2_grpc.HealthStub(channel)

            # Create a request
            request = hyperion_pb2.PingRequest(client_id="test-client")

            # Make the call
            print("Sending ping request...")
            start_time = time.time()
            response = stub.Ping(request)
            end_time = time.time()

            # Print the response
            print(f"Response received in {(end_time - start_time)*1000:.2f}ms")
            print(f"Status: {response.status}")
            print(f"Version: {response.version}")
            print(f"Server timestamp: {response.timestamp}")

            # Check response
            if response.status == "OK":
                print("Health check successful!")
                return 0
            else:
                print(f"Health check failed with status: {response.status}")
                return 1

        except grpc.RpcError as e:
            print(f"RPC error: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
