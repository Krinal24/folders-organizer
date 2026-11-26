import { useEffect, useState } from "react";
import { apiFetch, errorMessage, postJson } from "./api.js";
import { plural } from "./format.js";

async function fetchLearned() {
  const response = await apiFetch(`/learned`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Could not load your rules."));
  }
  return response.json();
}

function describeChoice(action, destination) {
  if (action === "keep") return "kept where it was";
  if (action === "delete") return "deleted";
  return destination ? `moved to ${destination}` : "moved";
}

export default function RulesView({ active }) {
  const [learned, setLearned] = useState(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmForget, setConfirmForget] = useState(false);

  // Refresh whenever the tab is opened or something changes.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    fetchLearned()
      .then((data) => {
        if (cancelled) return;
        setLearned(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not reach the backend.");
      });

    return () => {
      cancelled = true;
    };
  }, [active, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  const deleteRule = async (rule) => {
    const response = await apiFetch(`/rules/${rule.id}`, { method: "DELETE" });
    if (!response.ok) setError(await errorMessage(response, "Could not delete the rule."));
    reload();
  };

  const forget = async () => {
    const response = await apiFetch(`/corrections`, { method: "DELETE" });
    if (!response.ok) setError(await errorMessage(response, "Could not forget corrections."));
    setConfirmForget(false);
    reload();
  };

  return (
    <section className="rules">
      <div className="results-header">
        <div>
          <p className="eyebrow">WHAT TIDYBYTE HAS LEARNED</p>
          <h2>Your rules</h2>
        </div>
      </div>

      <p className="plan-notice">
        Rules are applied first, every time, without asking the AI. Create one
        here, or after changing a suggestion choose “Remember for similar files”.
      </p>

      {error && <p className="error">{error}</p>}

      <NewRuleForm onSaved={reload} />

      {learned?.rules.length === 0 && (
        <p className="history-empty">No rules yet.</p>
      )}

      <ul className="rule-list">
        {learned?.rules.map((rule) => (
          <li key={rule.id} className="rule-card">
            <span>
              Names containing <strong>“{rule.contains}”</strong>{" "}
              {rule.action === "keep" ? (
                "stay where they are"
              ) : (
                <>
                  go to <strong>{rule.destination}</strong>
                </>
              )}
            </span>
            <span className="rule-hits">
              {rule.hits > 0 ? `used ${plural(rule.hits, "time")}` : "not used yet"}
            </span>
            <button className="link-button" onClick={() => deleteRule(rule)}>
              Delete
            </button>
          </li>
        ))}
      </ul>

      {learned && (
        <div className="corrections">
          <h3>Learned from your corrections</h3>
          <p className="plan-notice">
            {learned.corrections === 0
              ? "When you change a suggestion and apply the plan, TidyByte remembers it. The AI then sees your most similar past choices as examples."
              : `TidyByte has learned from ${plural(learned.corrections, "correction")}. The AI sees the most similar ones as examples when it sorts new files.`}
          </p>

          {learned.recent_corrections.length > 0 && (
            <ul className="run-entries">
              {learned.recent_corrections.map((correction) => (
                <li key={correction.name + correction.at}>
                  <strong>{correction.name}</strong>: suggested{" "}
                  {describeChoice(correction.suggested_action, correction.suggested_destination)}
                  , you {describeChoice(correction.chosen_action, correction.chosen_destination)}
                </li>
              ))}
            </ul>
          )}

          {learned.corrections > 0 &&
            (confirmForget ? (
              <div className="run-confirm">
                <span>Forget all {plural(learned.corrections, "correction")}? Rules stay.</span>
                <button className="primary-button" onClick={forget}>
                  Forget them
                </button>
                <button className="link-button" onClick={() => setConfirmForget(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="link-button" onClick={() => setConfirmForget(true)}>
                Forget past corrections
              </button>
            ))}
        </div>
      )}
    </section>
  );
}

function NewRuleForm({ onSaved }) {
  const [contains, setContains] = useState("");
  const [action, setAction] = useState("move");
  const [destination, setDestination] = useState("");
  const [error, setError] = useState("");

  const save = async (event) => {
    event.preventDefault();
    const response = await postJson("/rules", {
      contains: contains.trim(),
      action,
      destination: action === "move" ? destination.trim() : null,
    });
    if (!response.ok) {
      setError(await errorMessage(response, "Could not save the rule."));
      return;
    }
    setContains("");
    setDestination("");
    setError("");
    onSaved();
  };

  return (
    <form className="new-rule" onSubmit={save}>
      <span>Names containing</span>
      <input
        aria-label="Text the file name contains"
        placeholder="e.g. 21MAT"
        value={contains}
        onChange={(event) => setContains(event.target.value)}
      />
      <select
        aria-label="What to do"
        value={action}
        onChange={(event) => setAction(event.target.value)}
      >
        <option value="move">go to</option>
        <option value="keep">stay where they are</option>
      </select>
      {action === "move" && (
        <input
          aria-label="Destination folder"
          placeholder="e.g. Documents/Study"
          value={destination}
          onChange={(event) => setDestination(event.target.value)}
        />
      )}
      <button
        type="submit"
        disabled={contains.trim().length < 2 || (action === "move" && !destination.trim())}
      >
        Add rule
      </button>
      {error && <span className="remember-error">{error}</span>}
    </form>
  );
}
