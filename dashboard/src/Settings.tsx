import { useState } from "react";
import type { Handler, PlatformSettings, SettingsRecord } from "./api";
import { postForRefusal } from "./api";
import { ConfirmDialog } from "./ConfirmDialog";
import { dateTime } from "./format";
import { ONLY_APPROVERS, useCanApprove } from "./handler";
import { useJson } from "./hooks";
import type { Field } from "./settingFields";
import { FIELDS, GROUPS, read, shown, stored, write } from "./settingFields";
import type { Theme } from "./theme";
import { chooseTheme, savedTheme } from "./theme";

/** The platform's settings: every handler sees them, an approver changes them. */
export function Settings() {
  const { data, error, reload } = useJson<SettingsRecord>("/api/settings");
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
  const canChange = useCanApprove();

  return (
    <section aria-labelledby="settings-heading">
      <h2 id="settings-heading">Settings</h2>
      <p className="muted">
        The rules the claim agent and the improver work to. A handler who can
        sign off payouts over the limit can change them, and each change is
        recorded.
      </p>
      {error && <p role="alert">The backend is not responding.</p>}
      {!error && !data && <p>Loading the settings</p>}
      {data && (
        <>
          {canChange ? (
            <SettingsForm settings={data.settings} onSaved={reload} />
          ) : (
            <ReadOnly settings={data.settings} />
          )}
          <Changes record={data} handlers={handlers} />
          <Models record={data} />
        </>
      )}
      <Appearance />
    </section>
  );
}

function ReadOnly({ settings }: Readonly<{ settings: PlatformSettings }>) {
  return (
    <div className="panel spaced">
      <p className="note">{ONLY_APPROVERS} can change the settings.</p>
      <dl className="facts settings-facts">
        {FIELDS.map((field) => (
          <FieldValue key={field.name} field={field} settings={settings} />
        ))}
      </dl>
    </div>
  );
}

function FieldValue({
  field,
  settings,
}: Readonly<{ field: Field; settings: PlatformSettings }>) {
  return (
    <>
      <dt>
        {GROUPS[field.group]}: {field.label}
      </dt>
      <dd className="mono">{shown(field, read(settings, field.name))}</dd>
    </>
  );
}

function SettingsForm({
  settings,
  onSaved,
}: Readonly<{ settings: PlatformSettings; onSaved: () => void }>) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const valueOf = (field: Field) =>
    draft[field.name] ?? String(stored(field, read(settings, field.name)));
  const changed = FIELDS.filter(
    (field) =>
      Number(valueOf(field)) !== stored(field, read(settings, field.name)),
  );

  const save = () => {
    let next = settings;
    for (const field of FIELDS) {
      next = write(next, field.name, Number(valueOf(field)) / field.scale);
    }
    setBusy(true);
    void postForRefusal("/api/settings", next, "PUT").then((refusal) => {
      setBusy(false);
      setConfirming(false);
      if (refusal) {
        setProblem(refusal);
        return;
      }
      setProblem("");
      setDraft({});
      onSaved();
    });
  };

  return (
    <form
      className="panel spaced settings-form"
      onSubmit={(event) => {
        event.preventDefault();
        setConfirming(true);
      }}
    >
      {Object.entries(GROUPS).map(([group, title]) => (
        <fieldset key={group}>
          <legend>{title}</legend>
          {FIELDS.filter((field) => field.group === group).map((field) => (
            <label key={field.name} className="setting">
              <span>{field.label}</span>
              <span className="setting-input">
                {field.unit === "$" && <span className="unit">$</span>}
                <input
                  type="number"
                  step="any"
                  min={0}
                  required
                  value={valueOf(field)}
                  onChange={(event) => {
                    setDraft({ ...draft, [field.name]: event.target.value });
                  }}
                />
                {field.unit !== "$" && (
                  <span className="unit">{field.unit}</span>
                )}
              </span>
              <span className="muted help">{field.help}</span>
            </label>
          ))}
        </fieldset>
      ))}
      {problem && <p role="alert">{problem}</p>}
      <div className="form-actions">
        <button type="submit" disabled={changed.length === 0}>
          Save changes
        </button>
        {changed.length > 0 && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setDraft({});
            }}
          >
            Discard
          </button>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title="Change the settings?"
          confirmLabel="Change the settings"
          busy={busy}
          onConfirm={save}
          onCancel={() => {
            setConfirming(false);
          }}
        >
          <ul>
            {changed.map((field) => (
              <li key={field.name}>
                {GROUPS[field.group]}, {field.label}:{" "}
                <span className="mono">
                  {shown(field, read(settings, field.name))}
                </span>{" "}
                to{" "}
                <span className="mono">
                  {shown(field, Number(valueOf(field)) / field.scale)}
                </span>
              </li>
            ))}
          </ul>
          <p className="muted">
            A new approval limit applies to the decisions made after it. A round
            already open keeps the settings it started with.
          </p>
        </ConfirmDialog>
      )}
    </form>
  );
}

function Changes({
  record,
  handlers,
}: Readonly<{ record: SettingsRecord; handlers: Handler[] | undefined }>) {
  return (
    <section className="panel spaced" aria-labelledby="changes-heading">
      <h3 id="changes-heading">Changes</h3>
      {record.changes.length === 0 ? (
        <p className="muted">
          No changes yet: the settings are as they started.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Who</th>
              <th scope="col">Setting</th>
              <th scope="col" className="number">
                From
              </th>
              <th scope="col" className="number">
                To
              </th>
            </tr>
          </thead>
          <tbody>
            {record.changes.map((change) => {
              const field = FIELDS.find((found) => found.name === change.name);
              return (
                <tr key={change.change_id}>
                  <td className="mono">{dateTime(change.changed_at)}</td>
                  <td>
                    {handlers?.find((h) => h.handler_id === change.handler_id)
                      ?.name ?? change.handler_id}
                  </td>
                  <td>
                    {field
                      ? `${GROUPS[field.group]}, ${field.label}`
                      : change.name}
                  </td>
                  <td className="mono number">
                    {field ? shown(field, change.before) : change.before}
                  </td>
                  <td className="mono number">
                    {field ? shown(field, change.after) : change.after}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Models({ record }: Readonly<{ record: SettingsRecord }>) {
  return (
    <section className="panel spaced" aria-labelledby="models-heading">
      <h3 id="models-heading">The models allowed</h3>
      <p className="muted">
        The models the claim agent may use, set by our IT team in{" "}
        <span className="mono">data/models.json</span>. Nobody can change them
        here, the improver included.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Reasoning efforts</th>
            <th scope="col" className="number">
              Input, per million tokens
            </th>
            <th scope="col" className="number">
              Output, per million tokens
            </th>
          </tr>
        </thead>
        <tbody>
          {record.models.map((model) => (
            <tr key={model.model}>
              <td className="mono">{model.model}</td>
              <td>{model.reasoning_efforts.join(", ")}</td>
              <td className="mono number">${model.input_price.toFixed(2)}</td>
              <td className="mono number">${model.output_price.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "The same as the computer" },
];

/** Light, dark or as the computer is, remembered by this browser. */
function Appearance() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  return (
    <section className="panel spaced" aria-labelledby="appearance-heading">
      <h3 id="appearance-heading">Appearance</h3>
      <div
        role="radiogroup"
        aria-labelledby="appearance-heading"
        className="themes"
      >
        {THEMES.map((choice) => (
          <label key={choice.value} className="theme-choice">
            <input
              type="radio"
              name="theme"
              value={choice.value}
              checked={theme === choice.value}
              onChange={() => {
                setTheme(choice.value);
                chooseTheme(choice.value);
              }}
            />
            {choice.label}
          </label>
        ))}
      </div>
      <p className="muted">This browser remembers your choice.</p>
    </section>
  );
}
