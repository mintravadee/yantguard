
import os

from groq import AsyncGroq


async def generate(prompt: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    if not api_key:
        raise RuntimeError("Groq API key is missing")

    async with AsyncGroq(
        api_key=api_key,
        timeout=30.0
    ) as client:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

    answer = response.choices[0].message.content

    if not isinstance(answer, str) or not answer:
        raise ValueError("Groq returned no text")

    usage = response.usage

    return {
        "provider": "groq",
        "model": model,
        "answer": answer,
        "usage": {
            "prompt_tokens": (
                usage.prompt_tokens if usage else 0
            ),
            "completion_tokens": (
                usage.completion_tokens if usage else 0
            ),
            "total_tokens": (
                usage.total_tokens if usage else 0
            ),
        },
    }
