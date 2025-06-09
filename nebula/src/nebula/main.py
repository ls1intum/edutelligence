from nebula.services.faq_service.faq_server import serve

if __name__ == "__main__":
    server = serve()
    print("FAQ service running on port 50051...")
    server.start()
    server.wait_for_termination()