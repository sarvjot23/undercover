"""The app's line to the agent, an AgentCore app: on the laptop at UNDERCOVER_AGENT,
or on AgentCore Runtime when UNDERCOVER_AGENT_RUNTIME names its ARN.

Each request is a payload naming an operation. The answer is one of four: the agent
took the work, refused it, didn't take it (the request never got there, or got an
error answer), or nobody knows (it was sent, then timed out or was cut off).
"""

import json
import logging
import os
import uuid
from typing import Any, Literal, NamedTuple

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

DEFAULT_URL = "http://127.0.0.1:8080"
TIMEOUT = 10
AWAY = "The agent isn't running"
UNKNOWN = (
    "The agent didn't answer in time. Reload the page to see whether it went through."
)
# Runtime: one attempt, since a retried call could start the same work twice, and
# answers inside Lambda's 30 seconds with time left for the app's own writes.
RUNTIME_CONFIG = Config(
    retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20
)
log = logging.getLogger(__name__)

Outcome = Literal["accepted", "refused", "not_taken", "unknown"]


class Answer(NamedTuple):
    """What became of a request: its outcome, the reason when there is one, and
    the agent's answer when it took the work."""

    outcome: Outcome
    detail: str
    body: dict[str, Any]


def read(body: dict[str, Any]) -> Answer:
    """The agent's answer: a refusal says why, anything else took the work."""
    if "refused" in body:
        return Answer("refused", str(body["refused"]), body)
    return Answer("accepted", "", body)


def on_laptop(payload: dict[str, Any]) -> Answer:
    """Post the payload to the agent's /invocations, with the agent's key."""
    url = os.getenv("UNDERCOVER_AGENT") or DEFAULT_URL
    key = os.getenv("UNDERCOVER_API_KEY", "")
    try:
        response = httpx.post(
            f"{url}/invocations",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.UnsupportedProtocol):
        return Answer("not_taken", AWAY, {})
    except httpx.HTTPError:
        return Answer("unknown", UNKNOWN, {})
    try:
        body = response.json()
    except ValueError:
        return Answer("unknown", UNKNOWN, {})
    if not response.is_success:
        return Answer("not_taken", str(body.get("error", AWAY)), body)
    return read(body)


def on_runtime(arn: str, payload: dict[str, Any]) -> Answer:
    """Invoke the agent's runtime with the payload, in a new session of its own."""
    runtime = boto3.client("bedrock-agentcore", config=RUNTIME_CONFIG)
    try:
        response = runtime.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=f"undercover-{uuid.uuid4().hex}",
            payload=json.dumps(payload),
        )
    except BotoConnectionError:
        return Answer("not_taken", AWAY, {})
    except ClientError as error:
        return Answer("not_taken", str(error), {})
    except BotoCoreError:
        return Answer("unknown", UNKNOWN, {})
    try:
        body = json.loads(response["response"].read())
    except (BotoCoreError, ValueError):
        return Answer("unknown", UNKNOWN, {})
    return read(body)


def send(payload: dict[str, Any]) -> Answer:
    """Send a payload to the agent on whichever route the settings give."""
    arn = os.getenv("UNDERCOVER_AGENT_RUNTIME")
    return on_runtime(arn, payload) if arn else on_laptop(payload)


def resume(claim_id: str) -> None:
    """Ask the agent to resume a paused claim with the handler's answer.

    The handler's answer stands either way; a call that fails is only logged.
    """
    answer = send({"operation": "resume_claim", "claim_id": claim_id})
    if answer.outcome != "accepted":
        log.warning(
            "The agent didn't take %s to resume it: %s", claim_id, answer.detail
        )
