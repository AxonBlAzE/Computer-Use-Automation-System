"""Trusted operator configuration, separate from untrusted capabilities."""

import re
from urllib.parse import urlsplit

from pydantic import Field

from automation.contracts import Model, Target


class PolicyDenied(Exception):
    pass


class Permission(Model):
    action: str
    target: Target


class Policy(Model):
    origin: str
    routes: list[str]
    permissions: list[Permission]
    timeout_ms: int = Field(default=3000, ge=100, le=30000)

    def check_url(self, url: str) -> None:
        actual, expected = urlsplit(url), urlsplit(self.origin)
        if (
            actual.scheme not in {"http", "https"}
            or (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc)
            or actual.username is not None
            or not any(re.fullmatch(route, actual.path) for route in self.routes)
        ):
            raise PolicyDenied("destination is not allowed")

    def url(self, path: str) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise PolicyDenied("navigation requires an origin-relative path")
        url = self.origin.rstrip("/") + path
        self.check_url(url)
        return url

    def check_action(self, action: str, target: Target) -> None:
        if not any(p.action == action and p.target == target for p in self.permissions):
            raise PolicyDenied("action and target are not allowlisted")
