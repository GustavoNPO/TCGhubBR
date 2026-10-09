import base64
import os

from io import BytesIO
from typing import Optional

from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


load_dotenv()


class CardExtraction(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Exact card name printed near the top of the card."
    )

    number: Optional[str] = Field(
        default=None,
        description="Printed collector number, for example 125/197."
    )

    local_id: Optional[str] = Field(
        default=None,
        description="The number before the slash. Example: 125 from 125/197."
    )

    set_name: Optional[str] = Field(
        default=None,
        description="Set name, only when readable from the card."
    )

    hp: Optional[int] = Field(
        default=None,
        description="Printed HP value if visible."
    )

    language: Optional[str] = Field(
        default=None,
        description="Card language, for example pt-br, en, es or ja."
    )

    confidence: float = Field(
        description="Confidence between 0 and 1 in the extracted identifying data."
    )


client = genai.Client()


PROMPT = """
You are reading a physical Pokemon Trading Card Game card.

Your job is TEXT EXTRACTION, not guessing the card from the artwork.

Read only information that is visible in the image.

The most important fields are:

1. Exact printed card name
2. Collector number, normally near the bottom of the card
3. Card language
4. HP
5. Set name if it is explicitly readable

For example:

If the card contains:

Charizard
180 HP
125/197

return:

name: Charizard
number: 125/197
local_id: 125
hp: 180

IMPORTANT:

- Do not identify a Pokemon only from its artwork.
- Do not invent unreadable information.
- If something cannot be read, return null.
- local_id is the portion before "/" in the collector number.
- confidence must represent how confident you are that the identifying text was read correctly.
"""


def prepare_image(image_bytes):
    image = Image.open(BytesIO(image_bytes))

    # Corrige fotos que vieram giradas do celular.
    image = ImageOps.exif_transpose(image)

    image = image.convert("RGB")

    # NÃ£o precisamos mandar uma foto de 4000x6000 para a IA.
    image.thumbnail((1600, 1600))

    output = BytesIO()

    image.save(
        output,
        format="JPEG",
        quality=90
    )

    return output.getvalue()


def extract_card_info(image_bytes):
    prepared_image = prepare_image(image_bytes)

    encoded_image = base64.b64encode(
        prepared_image
    ).decode("utf-8")

    interaction = client.interactions.create(
        model="gemini-3.5-flash-lite",

        input=[
            {
                "type": "text",
                "text": PROMPT
            },
            {
                "type": "image",
                "data": encoded_image,
                "mime_type": "image/jpeg"
            }
        ],

        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": CardExtraction.model_json_schema()
        }
    )

    result = CardExtraction.model_validate_json(
        interaction.output_text
    )

    return result