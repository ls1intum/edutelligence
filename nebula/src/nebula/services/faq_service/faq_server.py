import grpc
from concurrent import futures
from . import faq_pb2, faq_pb2_grpc
from ...services.faq_service.FaqRewritingService import FaqRewritingService

class FAQService(faq_pb2_grpc.FAQServiceServicer):

    def __init__(self):
        # Initialize the FAQ rewriter with the 'faq' variant
        self.faq_rewriter = FaqRewritingService(variant="faq")
        pass


    def ProcessInput(self, request, context):
        print(f"Received request - Input: {request.input_text}, FAQs: {request.faqs}")

        result = self.faq_rewriter.rewrite_faq(
            to_be_rewritten=request.input_text,
            # faqs=request.faqs  # Uncomment if your rewrite_faq accepts FAQs
        )

        # Here you would implement the logic to process the input text
        # For demonstration, we will just return a simple response

        return faq_pb2.FaqRewritingResponse(result="Processed the stuff: " + result)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Server started on port 50051")
    server.wait_for_termination()