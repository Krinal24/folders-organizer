import { formatBytes, plural } from "./format.js";

function describe(operations) {
  const moves = operations.filter((op) => op.action === "move");
  const deletes = operations.filter((op) => op.action === "delete");
  return {
    moves: moves.length,
    folders: new Set(moves.map((op) => op.destination)).size,
    deletes: deletes.length,
    deleteSize: deletes.reduce((total, op) => total + (op.size || 0), 0),
  };
}

function countResults(results) {
  const counts = { moved: 0, deleted: 0, skipped: 0, failed: 0 };
  for (const result of results.values()) {
    if (result.status === "done") {
      counts[result.action === "move" ? "moved" : "deleted"] += 1;
    } else {
      counts[result.status] += 1;
    }
  }
  return counts;
}

// Sticky bar under the plan while the user is still editing.
export function ApplyBar({ operations, execution }) {
  if (execution.phase !== "idle") return null;
  const { moves, folders, deletes, deleteSize } = describe(operations);

  return (
    <div className="apply-bar">
      <span>
        {operations.length === 0 ? (
          "Nothing to apply. Every item is set to keep or review."
        ) : (
          <>
            Ready: <strong>move {plural(moves, "file")}</strong>
            {moves > 0 && ` into ${plural(folders, "folder")}`}
            {" · "}
            <strong>delete {plural(deletes, "item")}</strong>
            {deletes > 0 && ` (${formatBytes(deleteSize)})`}
          </>
        )}
      </span>
      <button
        className="primary-button"
        disabled={operations.length === 0}
        onClick={execution.confirm}
      >
        Review & apply
      </button>
    </div>
  );
}

// Confirmation, progress and results, shown above the plan.
export function ApplyPanel({ operations, execution, onRescan, onShowHistory }) {
  if (execution.phase === "idle") return null;

  if (execution.phase === "confirming") {
    const { moves, folders, deletes, deleteSize } = describe(operations);
    return (
      <div className="apply-panel">
        <h3>Apply these changes?</h3>
        <ul className="apply-list">
          {moves > 0 && (
            <li>
              Move <strong>{plural(moves, "file")}</strong> into{" "}
              {plural(folders, "folder")} (created if needed)
            </li>
          )}
          {deletes > 0 && (
            <li>
              Send <strong>{plural(deletes, "item")}</strong> (
              {formatBytes(deleteSize)}) to the <strong>Recycle Bin</strong>
            </li>
          )}
        </ul>
        <p className="apply-fineprint">
          Nothing is overwritten: if a name is taken, the file gets a number
          like “report (1).pdf”. Files that changed since the scan are skipped.
          Moves can be undone afterwards.
        </p>
        <div className="apply-actions">
          <button className="primary-button" onClick={() => execution.run(operations)}>
            Apply {plural(operations.length, "change")}
          </button>
          <button className="link-button" onClick={execution.cancel}>
            Go back
          </button>
        </div>
      </div>
    );
  }

  const counts = countResults(execution.results);
  const processed = execution.results.size;

  if (execution.phase === "running") {
    return (
      <div className="apply-panel">
        <h3>Applying changes…</h3>
        <progress value={processed} max={execution.total} />
        <p className="apply-fineprint">
          {processed} of {execution.total} done · {counts.moved} moved ·{" "}
          {counts.deleted} deleted
          {counts.skipped + counts.failed > 0 &&
            ` · ${counts.skipped + counts.failed} not changed`}
        </p>
        <button className="link-button" onClick={execution.stop}>
          Stop
        </button>
      </div>
    );
  }

  const problems = [...execution.results.values()].filter(
    (result) => result.status !== "done"
  );
  const freed = execution.summary?.freed ?? 0;

  if (execution.phase === "undone") {
    const { restored, problems: undoProblems, in_recycle_bin } = execution.undoSummary;
    return (
      <div className="apply-panel">
        <h3>Moves undone</h3>
        <p>
          {plural(restored, "file")} moved back to where {restored === 1 ? "it was" : "they were"}.
          {in_recycle_bin > 0 &&
            ` ${plural(in_recycle_bin, "deleted item")} ${in_recycle_bin === 1 ? "is" : "are"} still in the Recycle Bin. Restore from there if needed.`}
        </p>
        {undoProblems.length > 0 && (
          <ProblemList title="Could not move back" items={undoProblems} />
        )}
        <button className="primary-button" onClick={onRescan}>
          Scan again
        </button>
      </div>
    );
  }

  return (
    <div className="apply-panel">
      <h3>
        {execution.stopped ? "Stopped" : execution.error ? "Something went wrong" : "Done"}
      </h3>
      {execution.error && <p className="error">{execution.error}</p>}
      <p>
        {plural(counts.moved, "file")} moved · {plural(counts.deleted, "item")} sent
        to the Recycle Bin
        {freed > 0 && ` (${formatBytes(freed)} freed)`}
        {problems.length > 0 && ` · ${plural(problems.length, "item")} not changed`}
      </p>

      {problems.length > 0 && (
        <ProblemList
          title="Not changed"
          items={problems.map((p) => `${p.relative_path}: ${p.detail}`)}
        />
      )}

      {execution.undoError && <p className="error">{execution.undoError}</p>}

      <div className="apply-actions">
        <button className="primary-button" onClick={onRescan}>
          Scan again
        </button>
        {counts.moved > 0 && execution.journalId && (
          <button
            className="secondary-button"
            onClick={execution.undo}
            disabled={execution.undoing}
          >
            {execution.undoing ? "Undoing…" : "Undo moves"}
          </button>
        )}
        {execution.journalId && (
          <button className="link-button" onClick={onShowHistory}>
            You can also undo later from History
          </button>
        )}
      </div>
    </div>
  );
}

function ProblemList({ title, items }) {
  return (
    <details className="problem-list">
      <summary>
        {title} ({items.length})
      </summary>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </details>
  );
}
