import type { ReactNode } from "react";
import { useEffect, useId, useRef } from "react";

/** The dashboard's own confirmation, before an action that changes the agent or a setting. */
export function ConfirmDialog({
  title,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
  children,
}: Readonly<{
  title: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}>) {
  const heading = useId();
  const confirm = useRef<HTMLButtonElement>(null);
  const cancel = useRef(onCancel);

  useEffect(() => {
    cancel.current = onCancel;
  });

  useEffect(() => {
    const field = document.querySelector<HTMLElement>(".dialog textarea");
    (field ?? confirm.current)?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel.current();
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
    };
  }, []);

  return (
    <div className="dialog-backdrop">
      <div
        className="panel dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
      >
        <h2 id={heading}>{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="dialog-actions">
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            ref={confirm}
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
