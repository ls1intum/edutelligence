import base64
from datetime import datetime
from typing import Literal, Any

import requests
from openai import OpenAI

from ...domain.pyris_image import PyrisImage
from ...llm.external.model import ImageGenerationModel


class OpenAIDalleWrapper(ImageGenerationModel):
    type: Literal["openai_dalle"]
    model: str
    _client: OpenAI

    def model_post_init(self, __context: Any) -> None:
        self._client = OpenAI(api_key=self.api_key)

    def generate_images(
        self,
        prompt: str,
        n: int = 1,
        size: Literal[
            "256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"
        ] = "256x256",
        quality: Literal["standard", "hd"] = "standard",
        **kwargs
    ) -> [PyrisImage]:
        response = self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=n,
            response_format="url",
            **kwargs
        )

        images = response.data
        iris_images = []
        for image in images:
            if image.revised_prompt is None:
                image.revised_prompt = prompt
            if image.b64_json is None:
                image_response = requests.get(image.url)
                image.b64_json = base64.b64encode(image_response.content).decode(
                    "utf-8"
                )

            iris_images.append(
                PyrisImage(
                    prompt=image.revised_prompt,
                    base64=image.b64_json,
                    timestamp=datetime.fromtimestamp(response.created),
                    raw_data=image,
                )
            )

        return iris_images