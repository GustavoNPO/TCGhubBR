import base64
import os

from io import BytesIO
from typing import Optional, Literal

from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


load_dotenv()


class CardExtraction(BaseModel):

    game: Literal[
        "pokemon",
        "magic",
        "digimon",
        "starwars",
        "unknown"
    ] = Field(
        description="Trading card game detected from the card."
    )

    printed_name: Optional[str] = Field(
        default=None,
        description=(
            "Exact card name as printed on the physical card."
        )
    )

    search_name: Optional[str] = Field(
        default=None,
        description=(
            "Canonical English name of the card if it can be "
            "confidently derived from the printed name. "
            "Do not infer it only from the artwork."
        )
    )

    collector_number: Optional[str] = Field(
        default=None,
        description=(
            "Collector number exactly as printed. "
            "Examples: 025/165, BT14-001, 123."
        )
    )

    local_id: Optional[str] = Field(
        default=None,
        description=(
            "Main identifying number of the card. "
            "For 025/165 return 025."
        )
    )

    language: Literal[
        "en",
        "pt-br",
        "es",
        "fr",
        "de",
        "it",
        "ja",
        "ko",
        "zh-tw",
        "zh-cn",
        "unknown"
    ] = Field(
        description="Language printed on the card."
    )

    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Confidence from 0 to 1 that the identifying "
            "information was read correctly."
        )
    )


client = genai.Client()


PROMPT = """
You are analyzing a photograph of a physical trading card.

Your job is to extract identifying information from the card.

SUPPORTED GAMES:

- pokemon
- magic
- digimon
- starwars
- unknown

SUPPORTED LANGUAGES:

- en
- pt-br
- es
- fr
- de
- it
- ja
- ko
- zh-tw
- zh-cn
- unknown


IMPORTANT RULES:

1. Determine which trading card game the card belongs to.

2. Read the exact card name printed on the card.

3. Detect the language printed on the card.

4. Read the collector/card number when visible.

5. If the printed name is not English, provide the canonical
English name in search_name ONLY when you are confident that it
can be derived from the printed name.

6. Do NOT identify a card only from the artwork.

7. Do NOT invent unreadable information.

8. Do NOT extract HP, attack damage, defense, mana cost,
power or other gameplay statistics.

9. confidence must represent how confident you are that the
identifying information was correctly read.

Examples:

A Pokemon card showing:

Pikachu
025/165

should produce information equivalent to:

game: pokemon
printed_name: Pikachu
search_name: Pikachu
collector_number: 025/165
local_id: 025
language: en


A Japanese Pokemon card showing:

リザードン
006/165

may produce:

game: pokemon
printed_name: リザードン
search_name: Charizard
collector_number: 006/165
local_id: 006
language: ja

Only provide search_name when you are confident about it.
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