import base64
from typing import List, Literal

import requests

from iris.domain.data.image_message_content_dto import ImageMessageContentDTO


def generate_images(
    self,
    prompt: str,
    n: int = 1,
    size: Literal[
        "256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"
    ] = "256x256",
    quality: Literal["standard", "hd"] = "standard",
    **kwargs,
) -> List[ImageMessageContentDTO]:
    """
    Generate images from the prompt.
    """
    try:
        response = self._client.images.generate(  # pylint: disable=protected-access
            model=self.model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=n,
            response_format="url",
            **kwargs,
        )
    except Exception as e:
        print(f"Failed to generate images: {e}")
        return []

    images = response.data
    iris_images = []
    for image in images:
        revised_prompt = (
            prompt if image.revised_prompt is None else image.revised_prompt
        )
        base64_data = image.b64_json
        if base64_data is None:
            try:
                image_response = requests.get(image.url, timeout=60)
                image_response.raise_for_status()
                base64_data = base64.b64encode(image_response.content).decode("utf-8")
            except requests.RequestException as e:
                print(f"Failed to download or encode image: {e}")
                continue

        iris_images.append(
            ImageMessageContentDTO(
                prompt=revised_prompt,
                pdfFile=base64_data,
            )
        )

    return iris_images
