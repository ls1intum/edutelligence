import grpc
from concurrent import futures
from . import faq_pb2, faq_pb2_grpc

class FAQService(faq_pb2_grpc.FAQServiceServicer):
    def ProcessInput(self, request, context):
        print("Received:", request.input_text)
        return faq_pb2.FaqRewritingResponse(result="Processed the stuff: " + request.input_text)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQService(), server)
    server.add_insecure_port('[::]:50051')
    return server