"""Evaluations: copies of a labelled set's claims, worked like any other claim."""

import json

from sqlalchemy import Connection, select

from backend.db import claims, handler_decisions, held_out_claims
from backend.schemas import SetName


def source_claims(conn: Connection, set_name: SetName, tiny: bool) -> list[dict]:
    """The claims of a labelled set, whole or just its tiny ones, in id order."""
    labelled = select(handler_decisions.c.claim_id).where(
        handler_decisions.c.set_name == set_name
    )
    if tiny:
        labelled = labelled.where(handler_decisions.c.tiny.is_(True))
    table = claims if set_name == "evaluation" else held_out_claims
    query = (
        select(table.c.body)
        .where(table.c.claim_id.in_(labelled))
        .order_by(table.c.claim_id)
    )
    return [json.loads(body) for body in conn.execute(query).scalars()]


def copy(conn: Connection, run_id: int, set_name: SetName, tiny: bool) -> list[str]:
    """Copy the set's claims for an evaluation, each with a new id in its record too."""
    copies = []
    for claim in source_claims(conn, set_name, tiny):
        copy_id = f"EV{run_id}-{claim['claim_id']}"
        conn.execute(
            claims.insert().values(
                claim_id=copy_id,
                status="waiting",
                body=json.dumps({**claim, "claim_id": copy_id}),
                attempts=0,
                evaluation_id=run_id,
                source_id=claim["claim_id"],
            )
        )
        copies.append(copy_id)
    return copies
