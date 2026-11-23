import httpx

from agents.application.analysis import InvalidModelOutput, ModelError


class LlamaCpp:
    def __init__(self, client: httpx.AsyncClient, endpoint: str, model: str) -> None:
        url = httpx.URL(endpoint)
        if (
            url.scheme != "http"
            or url.host not in {"127.0.0.1", "::1", "localhost"}
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("LLM_ENDPOINT must be a loopback HTTP URL.")
        self._client = client
        self._endpoint = endpoint.rstrip("/")
        self._model = model

    async def ready(self) -> bool:
        response = await self._client.get(
            f"{self._endpoint}/models", follow_redirects=False
        )
        response.raise_for_status()
        return any(model["id"] == self._model for model in response.json()["data"])

    async def complete(self, instructions: str, data: str) -> str:
        try:
            response = await self._client.post(
                f"{self._endpoint}/chat/completions",
                follow_redirects=False,
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": data},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 320,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > 4096:
                raise InvalidModelOutput("Invalid model output.")
            return content
        except httpx.TimeoutException as error:
            raise TimeoutError from error
        except httpx.HTTPError as error:
            raise ModelError("Local model request failed.") from error
        except (ValueError, LookupError, TypeError) as error:
            raise InvalidModelOutput("Invalid model response.") from error
