import { useEffect, useState } from "react";
import { API_URL, errorMessage, postJson } from "./api.js";
import { formatBytes, plural } from "./format.js";

async function fetchRuns() {
  const response = await fetch(`${API_URL}/runs`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Could not load history."));
  }
  return response.json();
}

export default function HistoryView({ active }) {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  // Refresh whenever the tab is opened or a run changes.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    fetchRuns()
      .then((data) => {
        if (cancelled) return;
        setRuns(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not reach the backend.");
      });

    return () => {
      cancelled = true;
    };
  }, [active, reloadKey]);

  const load = () => setReloadKey((key) => key + 1);

  return (
    <section className="history">
      <div className="results-header">
        <div>
          <p className="eyebrow">HISTORY</p>
          <h2>Past runs</h2>
        </div>
      </div>

      <p className="plan-notice">
        Every time you apply changes, TidyByte records what it moved and
        deleted. Moves can be undone here at any time. Deleted items stay in
        the Recycle Bin until you empty it.
      </p>

      {error && <p className="error">{error}</p>}

      {runs?.length === 0 && (
        <p className="history-empty">
          No runs yet. Changes you apply will show up here.
        </p>
      )}

      <div className="history-list">
        {runs?.map((run) => (
          <RunCard key={run.id} run={run} onChanged={load} />
        ))}
      </div>
    </section>
  );
}

function RunCard({ run, onChanged }) {
  const [details, setDetails] = useState(null);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [message, setMessage] = useState(null);

  const toggleDetails = async () => {
    setOpen(!open);
    if (!details) {
      const response = await fetch(`${API_URL}/runs/${run.id}`);
      if (response.ok) setDetails(await response.json());
    }
  };

  const undo = async () => {
    setUndoing(true);
    try {
      const response = await postJson("/undo", { journal_id: run.id });
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not undo."));
      }
      const result = await response.json();
      setMessage({
        ok: result.problems.length === 0,
        text:
          `${plural(result.restored, "file")} moved back.` +
          (result.problems.length
            ? ` ${plural(result.problems.length, "file")} could not be: ${result.problems.join("; ")}`
            : ""),
      });
      onChanged();
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setUndoing(false);
      setConfirming(false);
    }
  };

  const status = run.undone
    ? ["undone", "Undone"]
    : !run.completed
      ? ["stopped", "Stopped early"]
      : ["done", "Done"];

  return (
    <article className="run-card">
      <div className="run-header">
        <div className="run-title">
          <strong>{new Date(run.created * 1000).toLocaleString()}</strong>
          <span className="run-folder" title={run.root}>
            {run.root}
          </span>
        </div>
        <span className={`run-status status-${status[0]}`}>{status[1]}</span>
      </div>

      <p className="run-summary">
        {plural(run.moved, "file")} moved · {plural(run.deleted, "item")} sent to
        the Recycle Bin
        {run.freed > 0 && ` (${formatBytes(run.freed)} freed)`}
        {run.undone &&
          ` · undone ${new Date(run.undone.at * 1000).toLocaleString()}`}
      </p>

      {message && (
        <p className={message.ok ? "run-message" : "error"}>{message.text}</p>
      )}

      {confirming ? (
        <div className="run-confirm">
          <span>
            Move {plural(run.moved, "file")} back to where{" "}
            {run.moved === 1 ? "it was" : "they were"}?
            {run.deleted > 0 && " Deleted items stay in the Recycle Bin."}
          </span>
          <button className="primary-button" onClick={undo} disabled={undoing}>
            {undoing ? "Undoing…" : "Undo moves"}
          </button>
          <button className="link-button" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="run-actions">
          {run.can_undo && (
            <button className="secondary-button" onClick={() => setConfirming(true)}>
              Undo moves
            </button>
          )}
          <button className="link-button" onClick={toggleDetails}>
            {open ? "Hide details" : "Show details"}
          </button>
        </div>
      )}

      {open && details && (
        <ul className="run-entries">
          {details.entries.map((entry, index) => (
            <li key={index}>
              {entry.op === "move" ? (
                <>
                  <span className="entry-op op-move">Moved</span>
                  {entry.from} <span className="entry-arrow">→</span> {entry.to}
                </>
              ) : (
                <>
                  <span className="entry-op op-delete">Deleted</span>
                  {entry.path}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
