import { useState } from "react";
import type { Handler, RecipeDiff, RecipeVersion } from "./api";
import { DiffView } from "./DiffView";
import { byWhom, dateTime } from "./format";
import { useJson } from "./hooks";

/** The improver's recipe in its versions, each shown against the one before. */
export function Recipes() {
  const { data: recipes } = useJson<RecipeVersion[]>("/api/recipes", 10000);
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
  const [chosen, setChosen] = useState<number | null>(null);
  const shown = chosen ?? recipes?.[0]?.version ?? null;

  return (
    <section className="panel spaced" aria-labelledby="recipes-heading">
      <h3 id="recipes-heading">The recipe</h3>
      <p className="muted">
        The steps the improver follows. It proposes a better recipe at the end
        of each round, and a handler approves or rejects it.
      </p>
      {recipes ? (
        <ul className="recipe-versions">
          {recipes.map((recipe) => (
            <li key={recipe.version}>
              <button
                type="button"
                className="secondary"
                aria-pressed={recipe.version === shown}
                onClick={() => {
                  setChosen(recipe.version);
                }}
              >
                Recipe {recipe.version}
              </button>{" "}
              <span className="muted">
                {byWhom(recipe.proposed_by, handlers)}, approved by{" "}
                {byWhom(recipe.approved_by, handlers)} on{" "}
                <span className="mono">{dateTime(recipe.approved_at)}</span>.{" "}
                {recipe.reason}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="placeholder">Loading the recipe</p>
      )}
      {shown !== null && <RecipeChanges key={shown} version={shown} />}
    </section>
  );
}

function RecipeChanges({ version }: Readonly<{ version: number }>) {
  const { data: diff } = useJson<RecipeDiff>(
    `/api/recipes/${String(version)}/diff`,
  );
  if (!diff) return <p className="placeholder">Loading the changes</p>;
  return (
    <>
      <h4>
        {diff.before
          ? `Recipe ${String(version)} against recipe ${String(diff.before)}`
          : `Recipe ${String(version)}, the first`}
      </h4>
      <DiffView lines={diff.recipe} label={`Recipe ${String(version)}`} />
    </>
  );
}
