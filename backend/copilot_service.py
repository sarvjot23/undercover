"""The app's line to the Copilot, an AgentCore app of its own: on the laptop at
UNDERCOVER_COPILOT, or on AgentCore Runtime when UNDERCOVER_COPILOT_RUNTIME names its
ARN, with the conversation's id as the Runtime session.

Each payload carries the handler's sign-in, so nothing here logs a payload. The
Copilot needs no key: everything it does carries that sign-in, which the app checks.
"""

import json
import os
import time
from typing import Any

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

from backend.agent_service import RUNTIME_CONFIG, UNKNOWN, Answer, read

DEFAULT_URL = "http://127.0.0.1:8081"
TIMEOUT = 10
AWAY = "The Copilot isn't running"
# While Runtime starts or stops a session, a call gets a conflict that never reached
# the Copilot, so it's safe to try again.
CONFLICT = "ConflictException"
CONFLICT_ATTEMPTS = 4
CONFLICT_WAIT = 1.5


def on_laptop(payload: dict[str, Any]) -> Answer:
    """Post the payload to the Copilot's /invocations."""
    url = os.getenv("UNDERCOVER_COPILOT") or DEFAULT_URL
    try:
        response = httpx.post(f"{url}/invocations", json=payload, timeout=TIMEOUT)
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


def invoke(arn: str, session_id: str, payload: dict[str, Any]) -> Any:
    """Invoke the Copilot's runtime in the conversation's session, trying again
    while Runtime is starting or stopping that session."""
    runtime = boto3.client("bedrock-agentcore", config=RUNTIME_CONFIG)

    def call() -> Any:
        return runtime.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session_id,
            payload=json.dumps(payload),
        )

    for _ in range(CONFLICT_ATTEMPTS - 1):
        try:
            return call()
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != CONFLICT:
                raise
            time.sleep(CONFLICT_WAIT)
    return call()


def on_runtime(arn: str, session_id: str, payload: dict[str, Any]) -> Answer:
    """Send the payload to the Copilot's runtime."""
    try:
        response = invoke(arn, session_id, payload)
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


def send(conversation_id: str, payload: dict[str, Any]) -> Answer:
    """Send a payload to the Copilot on whichever route the settings give."""
    arn = os.getenv("UNDERCOVER_COPILOT_RUNTIME")
    if arn:
        return on_runtime(arn, conversation_id, payload)
    return on_laptop(payload)
