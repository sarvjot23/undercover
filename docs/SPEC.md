# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue

A dispatch works every claim left in progress and every waiting claim, oldest submitted first, with up to N claim agents working at once: from 1 to 25, with 3 to start with. Choosing the claims and keeping track of the dispatch is a fixed rule, with no model. Each claim is worked from a clean start and saves its progress as it goes. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error goes back in the queue and the same dispatch tries it once more, and a claim that fails twice is left for a handler. One bad claim never stops a dispatch. If a dispatch is stopped partway, the next one carries on the claims it left in progress, and that doesn't count as a new attempt. When the agent approves a payout that needs a sign-off, it keeps everything it has worked out and waits. As soon as a handler signs off, the agent picks the claim back up and pays it, and the payment records who signed off and when. A handler can only sign off for now. No claim is decided or paid twice, and only one dispatch or evaluation runs at a time. The agent can still be run on one named claim.

The tokens and cost of every model call, as OpenRouter reports them, and the time the agent spends working on each claim, which leaves out any wait for a sign-off, are recorded with the dispatch or evaluation they happened in.

An evaluation works copies of one of our two labelled sets, whole or just its five tiny claims, through the same dispatcher and claim agent, and scores the agent against our handlers' decisions. The copies never reach the queue, and nobody signs them off: an approval held for sign-off counts as finished.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The latest dispatch: each of its claims and where it stands, its model cost and time, and when it ends a summary built from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress.
- The swarm at work, live, one card for each claim.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, and the sections of the wording and the manual it read.
- A scoreboard of the evaluations, newest first, with decision accuracy, accuracy, the cost of mistakes, the straight-through rate, model cost per claim, time per claim and the time for the whole run, each opening to its claims with the handler's decision and payout beside the agent's.
- The claim agent's instructions, read only.

## Rules

- A payout over $800 needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- Decisions follow the policy wording, and the claims manual where the wording leaves a question open.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The agent must never see them.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Not for now

- No sign-in. Everyone who uses the screens sees everything.
- No real payments.
- No messages to customers.
