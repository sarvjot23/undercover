import asyncio

from backend import turns
from backend.turns import TakingTurns


def test_requests_beyond_the_limit_wait_their_turn_on_the_event_loop():
    inside = []
    most = []

    async def app(scope, receive, send):
        inside.append(1)
        most.append(len(inside))
        await asyncio.sleep(0.01)
        inside.pop()

    async def swarm():
        wrapped = TakingTurns(app)
        await asyncio.gather(
            *(wrapped({"type": "http"}, None, None) for _ in range(25))
        )

    asyncio.run(swarm())
    assert max(most) == turns.LIMIT == 8
    assert len(most) == 25


def test_other_traffic_goes_straight_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(TakingTurns(app)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]
