// The UnderCover Copilot: a sidebar on every signed-in page, where a handler asks in
// plain English and sees each step the Copilot takes as it takes it.
import type { KeyboardEvent } from "react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Handler } from "./api";
import type {
  Confirmation,
  Conversation,
  ConversationSummary,
  Turn,
} from "./conversations";
import { CopilotIcon, StepCard } from "./CopilotCards";
import {
  ask,
  boxPlaceholder,
  confirm,
  isWorking,
  linkClaims,
  SUGGESTIONS,
  turnLine,
  waitingFor,
} from "./conversations";
import { money } from "./format";
import { useJson } from "./hooks";

const POLL_MS = 1000;

/** Read the conversation every second while a turn works, and not while idle. */
const pollWhileWorking = (conversation: Conversation | null) =>
  conversation && isWorking(conversation) ? POLL_MS : 0;

function ConfirmationCard({
  card,
  onAnswer,
}: Readonly<{
  card: Confirmation;
  onAnswer: (confirmed: boolean) => Promise<void>;
}>) {
  const [sending, setSending] = useState(false);
  const answer = (confirmed: boolean) => {
    setSending(true);
    void onAnswer(confirmed).finally(() => {
      setSending(false);
    });
  };
  return (
    <section className="copilot-confirm" aria-label="Confirm the sign-off">
      <p className="confirm-title">Sign off and pay this claim?</p>
      <dl>
        <dt>Claim</dt>
        <dd className="mono">{card.claim_id}</dd>
        <dt>Customer</dt>
        <dd>{card.customer}</dd>
        <dt>Pays</dt>
        <dd className="mono">{money(card.amount)}</dd>
      </dl>
      <p className="confirm-reason">{card.reason}</p>
      <div className="confirm-actions">
        <button
          type="button"
          disabled={sending}
          onClick={() => {
            answer(true);
          }}
        >
          Sign off and pay
        </button>
        <button
          type="button"
          className="secondary"
          disabled={sending}
          onClick={() => {
            answer(false);
          }}
        >
          Cancel
        </button>
      </div>
    </section>
  );
}

function Answer({ turn }: Readonly<{ turn: Turn }>) {
  if (turn.status === "done" && turn.answer !== null) {
    return (
      <div className="copilot-answer">
        <div className="markdown">
          <Markdown remarkPlugins={[remarkGfm]}>
            {linkClaims(turn.answer)}
          </Markdown>
        </div>
        <p className="small-print">{turnLine(turn)}</p>
      </div>
    );
  }
  if (turn.status === "failed" || turn.status === "stopped") {
    const what =
      turn.status === "stopped"
        ? "The Copilot stopped before it finished."
        : `Something went wrong: ${turn.error ?? "the turn failed"}.`;
    return (
      <p className="copilot-problem" role="alert">
        {what} You can carry on with a new message.
      </p>
    );
  }
  return null;
}

function TurnView({
  turn,
  onAnswer,
}: Readonly<{
  turn: Turn;
  onAnswer: (confirmed: boolean) => Promise<void>;
}>) {
  return (
    <li className="copilot-turn">
      <p className="copilot-message">{turn.message}</p>
      {turn.steps.length > 0 && (
        <ul className="copilot-steps" aria-label="Steps">
          {turn.steps.map((step) => (
            <StepCard key={step.key} step={step} />
          ))}
        </ul>
      )}
      {turn.status === "working" && (
        <p className="copilot-working" role="status">
          <span className="dots" aria-hidden="true" />
          Working
        </p>
      )}
      {turn.status === "waiting" && turn.confirmation && (
        <ConfirmationCard card={turn.confirmation} onAnswer={onAnswer} />
      )}
      <Answer turn={turn} />
    </li>
  );
}

function Greeting({
  handler,
  onPick,
}: Readonly<{ handler: Handler | null; onPick: (text: string) => void }>) {
  const first = handler?.name.split(" ")[0];
  return (
    <div className="copilot-greeting">
      <p className="greeting-title">{first ? `Hello, ${first}.` : "Hello."}</p>
      <p className="muted">
        Ask about the queue, a claim, a customer or how the pilot is doing.
      </p>
      <ul className="suggestions">
        {SUGGESTIONS.map((text) => (
          <li key={text}>
            <button
              type="button"
              className="suggestion"
              onClick={() => {
                onPick(text);
              }}
            >
              {text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MessageBox({
  disabled,
  placeholder,
  onSend,
}: Readonly<{
  disabled: boolean;
  placeholder: string;
  onSend: (text: string) => void;
}>) {
  const [text, setText] = useState("");
  const send = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };
  return (
    <div className="copilot-box">
      <textarea
        aria-label="Ask the Copilot"
        placeholder={placeholder}
        value={text}
        rows={2}
        disabled={disabled}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={keyDown}
      />
      <button type="button" disabled={disabled || !text.trim()} onClick={send}>
        Send
      </button>
    </div>
  );
}

function History({
  conversations,
  current,
  onOpen,
}: Readonly<{
  conversations: ConversationSummary[];
  current: string | null;
  onOpen: (id: string) => void;
}>) {
  if (conversations.length === 0) {
    return <p className="muted copilot-history-empty">No conversations yet.</p>;
  }
  return (
    <ul className="copilot-history" aria-label="Earlier conversations">
      {conversations.map((found) => (
        <li key={found.conversation_id}>
          <button
            type="button"
            className="history-item"
            aria-current={
              found.conversation_id === current ? "true" : undefined
            }
            onClick={() => {
              onOpen(found.conversation_id);
            }}
          >
            {found.title}
          </button>
        </li>
      ))}
    </ul>
  );
}

function ConversationView({
  conversationId,
  handler,
  refusal,
  sending,
  onSend,
}: Readonly<{
  conversationId: string | null;
  handler: Handler | null;
  refusal: string | null;
  sending: boolean;
  onSend: (text: string) => void;
}>) {
  const { data: conversation, reload } = useJson<Conversation | null>(
    conversationId ? `/api/conversations/${conversationId}` : "",
    pollWhileWorking,
  );
  const body = useRef<HTMLDivElement>(null);
  const shown = conversationId ? conversation : null;
  const turns = shown?.turns ?? [];
  const lastSteps = turns.at(-1)?.steps.length ?? 0;
  useEffect(() => {
    const shownBody = body.current;
    if (shownBody) shownBody.scrollTop = shownBody.scrollHeight;
  }, [turns.length, lastSteps]);
  const waiting = waitingFor(shown ?? undefined);
  const working = sending || isWorking(shown ?? undefined);
  const onAnswer = async (confirmed: boolean) => {
    if (!conversationId) return;
    await confirm(conversationId, confirmed);
    reload();
  };
  return (
    <>
      <div className="copilot-body" ref={body}>
        {turns.length === 0 && !sending ? (
          <Greeting handler={handler} onPick={onSend} />
        ) : (
          <ol className="copilot-turns">
            {turns.map((turn) => (
              <TurnView key={turn.turn_id} turn={turn} onAnswer={onAnswer} />
            ))}
          </ol>
        )}
        {refusal && (
          <p className="copilot-problem" role="alert">
            {refusal}
          </p>
        )}
      </div>
      <MessageBox
        disabled={working || Boolean(waiting)}
        placeholder={boxPlaceholder(Boolean(waiting), working)}
        onSend={onSend}
      />
    </>
  );
}

/** The sidebar, open: the conversation, the earlier ones and the message box. */
export function Copilot({
  handler,
  onCollapse,
}: Readonly<{ handler: Handler | null; onCollapse: () => void }>) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [version, setVersion] = useState(0);
  const { data: conversations, reload } =
    useJson<ConversationSummary[]>("/api/conversations");

  const send = (text: string) => {
    setSending(true);
    setRefusal(null);
    void ask(conversationId, text).then((sent) => {
      setSending(false);
      if (sent.refusal !== undefined) {
        setRefusal(sent.refusal);
        return;
      }
      setConversationId(sent.conversation.conversation_id);
      setVersion((v) => v + 1);
      reload();
    });
  };

  return (
    <aside className="copilot" aria-label="Copilot">
      <div className="copilot-header">
        <span className="copilot-title">
          <CopilotIcon />
          Copilot
        </span>
        <button
          type="button"
          className="quiet"
          onClick={() => {
            setConversationId(null);
            setRefusal(null);
            setShowHistory(false);
          }}
        >
          New conversation
        </button>
        <button
          type="button"
          className="quiet"
          aria-expanded={showHistory}
          onClick={() => {
            setShowHistory(!showHistory);
          }}
        >
          Earlier
        </button>
        <button
          type="button"
          className="quiet copilot-collapse"
          aria-label="Collapse the Copilot"
          onClick={onCollapse}
        >
          »
        </button>
      </div>
      {showHistory && (
        <History
          conversations={conversations ?? []}
          current={conversationId}
          onOpen={(id) => {
            setConversationId(id);
            setRefusal(null);
            setShowHistory(false);
          }}
        />
      )}
      <ConversationView
        key={`${conversationId ?? "new"}-${String(version)}`}
        conversationId={conversationId}
        handler={handler}
        refusal={refusal}
        sending={sending}
        onSend={send}
      />
      <p className="copilot-foot muted">
        Signed in as <strong>{handler?.name ?? "a handler"}</strong>
      </p>
    </aside>
  );
}

/** The slim tab the sidebar collapses to. */
export function CopilotTab({ onOpen }: Readonly<{ onOpen: () => void }>) {
  return (
    <button
      type="button"
      className="copilot-tab"
      aria-label="Open the Copilot"
      onClick={onOpen}
    >
      <CopilotIcon />
      <span>Copilot</span>
    </button>
  );
}
