"""JWT + state snapshots for IMD AWS/ARG. No credential values live here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

from skyguard.config import REPO_ROOT

TOKEN_SKEW = timedelta(seconds=60)
DEFAULT_EXPIRES = timedelta(seconds=3600)


class ImdAuthError(RuntimeError):
    pass


@dataclass
class ImdCredentials:
    api_key: str
    email: str
    password: str
    token_url: str
    aws_url: str

    @property
    def complete(self) -> bool:
        return bool(self.api_key and self.email and self.password and self.token_url and self.aws_url)


def load_credentials() -> ImdCredentials:
    load_dotenv(REPO_ROOT / ".env", override=False)
    return ImdCredentials(
        api_key=os.environ.get("IMD_API_KEY", "").strip(),
        email=os.environ.get("IMD_EMAIL", "").strip(),
        password=os.environ.get("IMD_PASSWORD", "").strip(),
        token_url=os.environ.get("IMD_TOKEN_URL", "").strip(),
        aws_url=os.environ.get("IMD_AWS_URL", "").strip(),
    )


def redact(text: str, secrets: tuple[str, ...]) -> str:
    cleaned = text.replace("\n", " ")
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned[:240]


class ImdClient:
    """Refresh the bearer token before it expires. Each snapshot also sends the API key."""

    def __init__(
        self,
        credentials: ImdCredentials,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.credentials = credentials
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._client = httpx.Client(timeout=30.0, transport=transport)
        self._token: str | None = None
        self._refresh_at: datetime | None = None

    def close(self) -> None:
        self._client.close()

    def access_token(self) -> str:
        now = self._clock()
        if self._token is not None and self._refresh_at is not None and now < self._refresh_at:
            return self._token
        response = self._client.post(
            self.credentials.token_url,
            json={
                "email": self.credentials.email,
                "password": self.credentials.password,
                "api_key": self.credentials.api_key,
            },
        )
        if response.status_code != 200:
            raise ImdAuthError(
                f"IMD token HTTP {response.status_code}: "
                f"{redact(response.text, self._secrets())}"
            )
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ImdAuthError("IMD token response had no access_token")
        expires = body.get("expires_in")
        try:
            lifetime = timedelta(seconds=int(expires))
        except (TypeError, ValueError):
            lifetime = DEFAULT_EXPIRES
        self._token = token
        self._refresh_at = now + lifetime - TOKEN_SKEW
        return token

    def fetch_state(self, state_id: int) -> list[dict[str, Any]]:
        response = self._client.get(
            self.credentials.aws_url,
            params={"sid": str(state_id)},
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "X-API-KEY": self.credentials.api_key,
            },
        )
        if response.status_code != 200:
            raise ImdAuthError(
                f"IMD aws_data sid={state_id} HTTP {response.status_code}: "
                f"{redact(response.text, self._secrets())}"
            )
        payload = response.json()
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("data")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        raise ImdAuthError(f"IMD aws_data sid={state_id} was not a list of stations")

    def _secrets(self) -> tuple[str, ...]:
        return (self.credentials.api_key, self.credentials.email, self.credentials.password, self._token or "")
