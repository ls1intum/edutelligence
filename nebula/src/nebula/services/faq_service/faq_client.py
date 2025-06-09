import grpc
from nebula.services.faq_service import faq_pb2, faq_pb2_grpc

def send_input():
    channel = grpc.insecure_channel("localhost:50051")
    stub = faq_pb2_grpc.FAQServiceStub(channel)

    faqs = [faq_pb2.FAQ(question_title="What?", question_answer="This.")]
    response = stub.ProcessInput(faq_pb2.FaqRewritingRequest(faqs=faqs, input_text="Check this"))
    print("Response:", response.result)

if __name__ == "__main__":
    send_input()