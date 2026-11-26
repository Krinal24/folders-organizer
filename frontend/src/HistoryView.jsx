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
        deleted. Undo a whole run or just some of its files, at any time:
        moved files go back where they were, and deleted ones come back out
        of the Recycle Bin, as long as it hasn't been emptied.
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

function describeUndo(result) {
  const parts = [
    result.restored > 0 && `${plural(result.restored, "file")} moved back`,
    result.recovered > 0 &&
      `${plural(result.recovered, "item")} restored from the Recycle Bin`,
  ].filter(Boolean);
  let text = parts.length ? `${parts.join(" · ")}.` : "Nothing could be put back.";
  if (result.problems.length) {
    text += ` ${plural(result.problems.length, "item")} could not be: ${result.problems.join("; ")}`;
  }
  return { ok: result.problems.length === 0, text };
}

async function fetchRun(id) {
  const response = await fetch(`${API_URL}/runs/${id}`);
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Could not load this run."));
  }
  return response.json();
}

function RunCard({ run, onChanged }) {
  const [details, setDetails] = useState(null);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [confirming, setConfirming] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [message, setMessage] = useState(null);

  const loadDetails = () =>
    fetchRun(run.id)
      .then(setDetails)
      .catch((err) => setMessage({ ok: false, text: err.message }));

  const toggleDetails = () => {
    setOpen(!open);
    if (!details) loadDetails();
  };

  const canUndo = (entry) =>
    !entry.undone && (entry.op === "move" || run.can_restore_deletes);
  const undoable = details
    ? details.entries.map((entry, index) => (canUndo(entry) ? index : null)).filter((i) => i !== null)
    : [];

  const toggle = (index) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  const toggleAll = () =>
    setSelected(selected.size === undoable.length ? new Set() : new Set(undoable));

  const undo = async (entries) => {
    setUndoing(true);
    try {
      const response = await postJson("/undo", { journal_id: run.id, entries });
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not undo."));
      }
      setMessage(describeUndo(await response.json()));
      setSelected(new Set());
      if (details) loadDetails();
      onChanged();
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setUndoing(false);
      setConfirming(false);
    }
  };

  const status = !run.can_undo && run.undone > 0
    ? ["undone", "Undone"]
    : run.undone > 0
      ? ["partly", "Partly undone"]
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
        {run.undone > 0 &&
          ` · ${run.undone} undone, last ${new Date(run.undone_at * 1000).toLocaleString()}`}
      </p>

      {message && (
        <p className={message.ok ? "run-message" : "error"}>{message.text}</p>
      )}

      {confirming ? (
        <div className="run-confirm">
          <span>
            Undo {run.pending === 1 ? "the remaining change" : `all ${run.pending} remaining changes`}?
            {" "}Moved files go back where they were
            {run.deleted > 0 &&
              (run.can_restore_deletes
                ? " and deleted items come back from the Recycle Bin"
                : "; restore deleted items from the Trash by hand")}
            .
          </span>
          <button className="primary-button" onClick={() => undo(null)} disabled={undoing}>
            {undoing ? "Undoing…" : "Undo all"}
          </button>
          <button className="link-button" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="run-actions">
          {run.can_undo && (
            <button className="secondary-button" onClick={() => setConfirming(true)}>
              Undo all
            </button>
          )}
          <button className="link-button" onClick={toggleDetails}>
            {open ? "Hide details" : run.can_undo ? "Choose files to undo" : "Show details"}
          </button>
        </div>
      )}

      {open && details && (
        <>
          {undoable.length > 0 && (
            <div className="run-select-bar">
              <label>
                <input
                  type="checkbox"
                  checked={selected.size === undoable.length}
                  onChange={toggleAll}
                />
                Select all
              </label>
              <button
                className="primary-button"
                onClick={() => undo([...selected])}
                disabled={selected.size === 0 || undoing}
              >
                {undoing ? "Undoing…" : `Undo selected (${selected.size})`}
              </button>
            </div>
          )}
          <ul className="run-entries">
            {details.entries.map((entry, index) => (
              <li key={index} className={entry.undone ? "entry-undone" : undefined}>
                {canUndo(entry) ? (
                  <input
                    type="checkbox"
                    aria-label={`Undo ${entry.from || entry.path}`}
                    checked={selected.has(index)}
                    onChange={() => toggle(index)}
                  />
                ) : (
                  <span className="entry-check-placeholder" />
                )}
                {entry.op === "move" ? (
                  <span>
                    <span className="entry-op op-move">Moved</span>
                    {entry.from} <span className="entry-arrow">→</span> {entry.to}
                  </span>
                ) : (
                  <span>
                    <span className="entry-op op-delete">Deleted</span>
                    {entry.path}
                  </span>
                )}
                {entry.undone && <span className="entry-undone-tag">Undone</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
