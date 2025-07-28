import logging

logger = logging.getLogger("nebula.faq.rewrite_service")


def send_rewritten_faq(rewritten_text: str, user_id: int, course_id: int):
    logger.info(
        "Sending rewritten FAQ to the database with text: '%s', user_id: %d, course_id: %d",
        rewritten_text,
        user_id,
        course_id,
    )
    #   Here you call the Artemis API to send the rewritten text back to the main application.
    # For example:
    # response = requests.post(
    #     f"{ARTEMIS_API_BASE_URL}/api/faq/rewrite",
    #     json={
    #         "rewrittenText": rewritten_text,
    #         "userId": user_id,
    #         "courseId": course_id,
    #     },
    #     headers={"Authorization
    #         f"Bearer {ARTEMIS_API_KEY}"}
    # )

    # if response.status_code != 200:
    #     logger.error("Failed to send rewritten FAQ: %s", response.text)

def rewrite_faq_text(to_be_rewritten: str, faqs: list) -> str:
    logger.info("Rewriting FAQ text with input: '%s' and %d FAQs", to_be_rewritten, len(faqs))
    # Here you would implement the logic to rewrite the FAQ text using the provided input and FAQs.
    # This is a placeholder implementation.
    rewritten_text = f"Rewritten FAQ based on input: {to_be_rewritten} and FAQs: {faqs}"
    return rewritten_text









