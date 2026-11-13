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

## What the agent works from

- **Our records**, the system of record: claims, policies, customers, decisions and payments. The agent reaches them only through our app, and only for the claim it's working on, its policy and its customer (claims manual section 11).
- **The context layer**: the business's definitions, plans, claim rules, outside facts such as named storms, strikes and prices, and the policy wording and claims manual, a section at a time. Data governance owns these files in `context/`, each naming its system, owner and review date, and the agent only reads them.
- **Its memory of each customer**, in AgentCore Memory: the claims and decisions of the customer's earlier claims, never their stories or documents. Each customer's memories are used only for their own claims, nothing is remembered from a claim the security check referred or from an evaluation, and evaluations run without memory. Our claim history still counts for repeat claims (manual section 9).

When the AgentCore Gateway is set up, the agent's tools and the payment go through it, so its Policy covers them; otherwise they go straight to the app and the context layer. A payment the Gateway refuses waits for a handler's sign-off, which pays it.

## Working the queue

A dispatch works every claim left in progress and every waiting claim, oldest submitted first, with up to N claim agents working at once: from 1 to 25, with 3 to start with. Choosing the claims and keeping track of the dispatch is a fixed rule, with no model. Each claim is worked from a clean start and saves its progress as it goes. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error goes back in the queue and the same dispatch tries it once more, and a claim that fails twice is left for a handler. One bad claim never stops a dispatch. If a dispatch is stopped partway, the next one carries on the claims it left in progress, and that doesn't count as a new attempt. When the agent approves a payout that needs a sign-off, it keeps everything it has worked out and waits. A handler's sign-off pays the claim at once, and the payment records who signed off and when; the agent then only closes its paused work and pays nothing. A handler who thinks the decision is wrong can instead send it back to the agent with a note saying what to look at again: the decision is kept with the note, who sent it back and when, the claim is sent back, and the agent takes it, reads the note as a senior handler's review, checks it against the wording and the manual like everything else, and decides again. The new decision goes through the same rules, and a claim can be sent back more than once. A sent-back claim the agent never received is worked by the next dispatch. No claim is decided or paid twice, and only one dispatch or evaluation runs at a time. The agent can still be run on one named claim.

The tokens and cost of every model call, as OpenRouter reports them, and the time the agent spends working on each claim, which leaves out any wait for a sign-off, are recorded with the dispatch or evaluation they happened in.

An evaluation works copies of one of our two labelled sets, whole or just its five tiny claims, through the same dispatcher and claim agent, and scores the agent against our handlers' decisions. The copies never reach the queue, and nobody signs them off: an approval held for sign-off counts as finished.

## Improving the agent

The claim agent's instructions, model and reasoning effort make up its configuration, kept in versions. Each version records what changed, the reason, who proposed it and who approved it and when. A dispatch and an evaluation each record the version they used: a dispatch, an evaluation started on the Scoreboard and a run of the agent on one claim always use the current version.

A second agent, the improver, improves the claim agent in rounds, following a recipe that it improves at the end of each round. A handler who can sign off payouts over the limit starts a round, can stop it, and approves or rejects each of the improver's proposals: nothing it proposes takes effect until then, and a rejection carries the handler's reason back to it. A round works to the settings as they stood when it started.

- A version's scores are the averages of the whole-set evaluations that rounds ran on it. A round first runs any the current version is missing: one on the evaluation set, two on the held-out set.
- The improver reads the current version and its scores, the claims it got wrong on the evaluation set and the five right ones it explained least well, with our handlers' decisions and reasons beside the agent's and the judge's grade, the earlier rounds, our objectives, noise, tolerance and rule, what's left of the round's spending limit and the models allowed. From the held-out set it sees the scores only.
- An approved change is evaluated once on the evaluation set and twice on the held-out set. It is kept when its held-out average meets our objectives, at least one measure improves by more than its noise and none gets worse by more than its tolerance; otherwise it is rolled back, as is a version with no grade, one whose evaluations were stopped, or one the round can't afford. A kept version becomes the current version.
- A judge, Jev, grades each of an evaluation's explanations against the handler's reason and reference, from F to A, with whether the agent gave the same grounds and the same section. A claim the agent didn't decide gets an F.
- Each round has a spending limit that covers the improver, all its evaluations and the judge. An evaluation likely to cost more than what's left is refused, and once the limit is spent no new claim starts in its evaluations.
- The improver can't change our objectives, the noise and tolerance, the spending limit, the models allowed, the approval limit, the evaluation sets or the judge.

## Settings

The approval limit, the business objectives (floors on held-out accuracy and the judge's grade), the noise and tolerance for accuracy, the grade, cost per claim and time per claim, a round's spending limit and the claim agents at once in its evaluations are the platform's settings. Every handler can see them, and a handler who can sign off payouts over the limit can change them. Each change records who made it and when. The models the claim agent may use, with their reasoning efforts and prices, are set by our IT team and can't be changed on the page.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, sent back, decided or left for a handler.
- The latest dispatch: each of its claims and where it stands, its model cost and time, and when it ends a summary built from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress.
- The swarm at work, live, one card for each claim.
- Each claim in full, with the agent's decision and its reasons, and each decision sent back with its note, who sent it back and when.
- What the agent is doing on a claim while it works, step by step: each tool call, each lookup in the context layer with where it came from, each search of or save to memory, and each refusal, labeled by who refused. A Context used panel lists everything it looked up, once each, by file with each file's source, and the decision panel shows the whole decision record with the calculation line by line.
- A scoreboard of the evaluations, newest first, with decision accuracy, accuracy, the cost of mistakes, the straight-through rate, model cost per claim, time per claim and the time for the whole run, each opening to its claims with the handler's decision and payout beside the agent's.
- The claim agent's configuration: the current version, every version with its held-out scores, and what any version changed from the one before.
- The improvement of the agent: where a round has got to as it happens, the proposal waiting with its changes, the rounds so far with their scores before and after, verdicts, approvals and cost, a chart of each version tried, and the recipe's versions.
- The settings, and who changed what.
- Every page needs a handler signed in with their email and password. The header shows who is signed in, with a way to sign out.

## Rules

- A payout over the approval limit, a setting that starts at $800, needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay. A new limit applies to the decisions recorded after it.
- Only a handler who can sign off payouts over the limit may sign one off or send it back, start or stop a round, approve or reject the improver's proposals or change a setting. Today that is Dana Whitfield; Marcus Oyelaran and Priya Raman can't. The pages say what they can't do and why, and the system refuses it too.
- Before the agent works a claim, a check reads what the customer wrote for instructions to the AI hidden in it. A claim with any is referred to a handler with a payout of 0 and the check's reason, and the agent never reads it. The check can't be changed by the improver.
- The agent's calls to the backend carry an API key of its own. The routes only the agent uses refuse a call without it, the reads it shares with the dashboard take the key or a signed-in handler, and the key never stands in for a handler. The agent's own API is described in an OpenAPI document of exactly its six operations.
- Decisions follow the policy wording, and the claims manual where the wording leaves a question open.
- Every decision record holds the decision, the payout, the calculation for an approval, the section relied on, a reason in plain language, who or what made it (the UnderCover Agent with its version, or the security check), when, and the claims manual's version in force (claims manual sections 13 and 14). A sign-off adds who signed off and when. A record that falls short is refused with what's missing, and an approval must pay exactly what its calculation for that attempt says.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The claim agent must never see them. The improver reads our handlers' decisions and reasons on the evaluation set, and nothing in the agent reads the held-out set's.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the handlers and the company's settings. The plans, the policy wording and the claims manual come from data governance's files in `context/`. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Not for now

- No real payments.
- No messages to customers.
