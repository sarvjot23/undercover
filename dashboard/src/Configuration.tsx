import { useState } from "react";
import type { ConfigVersion, Handler, VersionDiff, VersionScores } from "./api";
import { DiffView } from "./DiffView";
import { byWhom, dateTime, percent } from "./format";
import { useJson } from "./hooks";
import { Badge, ErrorState, LoadingState, PageHeader } from "./ui";

function score(found: VersionScores | null, name: "accuracy" | "grade") {
  const value = found?.[name];
  if (value === undefined || value === null) return "None yet";
  return name === "accuracy" ? percent(value) : value.toFixed(2);
}

/** The claim agent's configuration: the current version, every version, and its diff. */
export function Configuration() {
  const {
    data: versions,
    error,
    reload,
  } = useJson<ConfigVersion[]>("/api/configuration/versions", 5000);
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
  const [chosen, setChosen] = useState<number | null>(null);

  if (error) return <ErrorState onRetry={reload} />;
  if (!versions) return <LoadingState what="the configuration" />;

  const current = versions.find((version) => version.current);
  const shown = chosen ?? current?.version ?? 1;

  return (
    <section aria-labelledby="configuration-heading">
      <PageHeader title="Configuration" id="configuration-heading">
        The claim agent&rsquo;s instructions, model and reasoning effort, kept
        in versions. Read only: a new version comes from the improver, once a
        handler approves it.
      </PageHeader>
      {current && (
        <div className="panel current-version">
          <h3>Version {current.version}, the current version</h3>
          <dl className="facts">
            <dt>Model</dt>
            <dd className="mono">{current.model}</dd>
            <dt>Reasoning effort</dt>
            <dd>{current.reasoning}</dd>
            <dt>Held-out accuracy</dt>
            <dd className="mono">
              {score(current.scores.held_out, "accuracy")}
            </dd>
          </dl>
          <details>
            <summary>The instructions</summary>
            <pre className="instructions">{current.instructions}</pre>
          </details>
        </div>
      )}
      <div className="panel spaced table-panel">
        <table aria-label="Versions">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Model and effort</th>
              <th scope="col">What changed</th>
              <th scope="col">Reason</th>
              <th scope="col">Proposed by</th>
              <th scope="col">Approved</th>
              <th scope="col" className="number">
                Held-out accuracy
              </th>
              <th scope="col" className="number">
                Held-out grade
              </th>
              <th scope="col">
                <span className="visually-hidden">Diff</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr
                key={version.version}
                className={version.version === shown ? "chosen" : undefined}
              >
                <td className="mono">
                  {version.version}
                  {version.current && <Badge tone="gold">Current</Badge>}
                </td>
                <td>
                  <span className="mono">{version.model}</span>{" "}
                  {version.reasoning}
                </td>
                <td>
                  {version.changed.length > 0
                    ? version.changed.join(", ")
                    : "The first version"}
                </td>
                <td className="summary">{version.reason}</td>
                <td>{byWhom(version.proposed_by, handlers)}</td>
                <td>
                  {byWhom(version.approved_by, handlers)},{" "}
                  <span className="mono">{dateTime(version.approved_at)}</span>
                </td>
                <td className="mono number">
                  {score(version.scores.held_out, "accuracy")}
                </td>
                <td className="mono number">
                  {score(version.scores.held_out, "grade")}
                </td>
                <td>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setChosen(version.version);
                    }}
                    aria-pressed={version.version === shown}
                  >
                    Show the changes
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <VersionChanges key={shown} version={shown} />
    </section>
  );
}

/** What one version changed from the one before. */
function VersionChanges({ version }: Readonly<{ version: number }>) {
  const { data: diff } = useJson<VersionDiff>(
    `/api/configuration/versions/${String(version)}/diff`,
  );
  return (
    <section className="panel spaced" aria-labelledby="changes-heading">
      <h3 id="changes-heading">
        {diff?.before
          ? `Version ${String(version)} against version ${String(diff.before)}`
          : `Version ${String(version)}`}
      </h3>
      {diff ? (
        <>
          <ModelChange
            label="Model"
            before={diff.model[0]}
            after={diff.model[1]}
          />
          <ModelChange
            label="Reasoning effort"
            before={diff.reasoning[0]}
            after={diff.reasoning[1]}
          />
          <DiffView
            lines={diff.instructions}
            label={`The instructions in version ${String(version)}`}
          />
        </>
      ) : (
        <LoadingState what="the changes" />
      )}
    </section>
  );
}

/** A model or effort before and after, or as it stays. */
export function ModelChange({
  label,
  before,
  after,
}: Readonly<{ label: string; before: string | null; after: string }>) {
  return (
    <p className="model-change">
      <span className="muted">{label}:</span>{" "}
      {before === null || before === after ? (
        <span className="mono">{after}</span>
      ) : (
        <>
          <del className="mono">{before}</del> to{" "}
          <ins className="mono">{after}</ins>
        </>
      )}
    </p>
  );
}
