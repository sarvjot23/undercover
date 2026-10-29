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

One run of the agent works the whole queue, or a capped number of claims for a trial, with the rest left waiting. It chooses the order, plans the run as a to-do list the team can watch, and hands each claim to a helper that works it from a clean start and reports back in a line. It finishes with a short summary for the handlers. A claim that fails partway goes back in the queue to be tried again, and a claim that fails twice is left for a handler. No claim is decided or paid twice, and a run cannot finish while a claim within its cap is still waiting. The agent can still be run on one named claim.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The current run's to-do list, and the agent's summary when it ends.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, and the sections of the wording and the manual it read.
- The agent's instructions for running the queue and for working a claim, read only.

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
