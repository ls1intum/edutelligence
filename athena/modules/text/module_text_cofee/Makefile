all: python_client

python_client: cofee.proto
	protoc --version || (echo "Please install protoc: https://grpc.io/docs/protoc-installation/"; exit 1)
	protoc --python_out ./module_text_cofee/protobuf/ cofee.proto

clean:
	rm -f ./module_text_cofee/protobuf/cofee_pb2.py