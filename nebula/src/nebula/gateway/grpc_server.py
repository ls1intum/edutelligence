import logging
import grpc
from concurrent import futures

from nebula.grpc_stubs import faq_pb2_grpc
from nebula.gateway.faq_handler import FAQServiceHandler


logger = logging.getLogger("nebula.gateway")
logging.basicConfig(level=logging.INFO)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # FAQ-Handler registrieren
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQServiceHandler(), server)
    #(später) Weitere Handler registrieren
    # transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(TranscriptionServiceHandler(), server)
    logger.info("🔗 gRPC-Handler für FAQ rewriting registriert")
    server.add_insecure_port("[::]:50051")
    logger.info("🚀 gRPC server run on Port 50051")
    server.start()
    server.wait_for_termination()
