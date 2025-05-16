#!/usr/bin/env python
"""
Simple client to test the Health service of the gRPC server.

Usage:
    poetry run health-check
"""

import sys
import grpc
import time
from app.grpc import hyperion_pb2, hyperion_pb2_grpc

def main():
    """Test the Health service by sending a Ping request."""
    # Create a gRPC channel
    print(f"Connecting to gRPC server at...")

    with grpc.insecure_channel("0.0.0.0:50051") as channel:
        try:
            # Create a stub (client)
            stub = hyperion_pb2_grpc.HealthStub(channel)

            # Create a request
            request = hyperion_pb2.PingRequest(client_id="health-client")

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
