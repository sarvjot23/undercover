"""The Gateway route: every tool call through the AgentCore Gateway, as its MCP tools,
signed with AWS Signature Version 4 with the AWS CLI's credentials and region."""

from collections.abc import Generator
from typing import Any

import boto3
import httpx
from botocore.auth import SigV4Auth as BotocoreSigV4Auth
from botocore.awsrequest import AWSRequest

from agent import mcp_bridge

SERVICE = "bedrock-agentcore"
REFUSED_BY = {"undercover-app": "the app", "undercover-context": "the context layer"}


class SigV4Auth(httpx.Auth):
    """Sign each request as boto3 signs its own calls."""

    requires_request_body = True

    def __init__(self, session: boto3.Session) -> None:
        self.credentials = session.get_credentials()
        self.region = session.region_name

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        headers = {
            "Host": request.url.netloc.decode(),
            "Content-Type": request.headers.get("content-type", ""),
        }
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=headers,
        )
        BotocoreSigV4Auth(
            self.credentials.get_frozen_credentials(), SERVICE, self.region
        ).add_auth(signed)
        for name in ("Authorization", "X-Amz-Date", "X-Amz-Security-Token"):
            if name in signed.headers:
                request.headers[name] = signed.headers[name]
        yield request


class Gateway:
    """The Gateway at its URL, which names each tool <target>___<operation>."""

    name = "gateway"

    def __init__(self, url: str, auth: httpx.Auth | None = None) -> None:
        self.server = mcp_bridge.Server(
            url, auth or SigV4Auth(boto3.Session()), "the Gateway"
        )

    def tool_name(self, target: str, operation: str) -> str:
        """The Gateway's name for a target's operation."""
        return f"{target}___{operation}"

    def call(self, target: str, operation: str, arguments: dict[str, Any]) -> str:
        """Call one tool through the Gateway, or raise Refused with who refused it."""
        return mcp_bridge.call(
            self.server,
            self.tool_name(target, operation),
            arguments,
            REFUSED_BY[target],
        )
