import { useRef, useState } from "react";
import { errorMessage, postJson, readNdjson } from "./api.js";

const IDLE = { phase: "idle", results: new Map() };

// Runs the approved operations on the backend and tracks per-file results.
export function useExecution(path) {
  const [state, setState] = useState(IDLE);
  const abortRef = useRef(null);

  const update = (changes) => setState((current) => ({ ...current, ...changes }));

  const run = async (operations) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ phase: "running", results: new Map(), total: operations.length });

    try {
      const response = await postJson(
        "/execute",
        { path, operations },
        { signal: controller.signal }
      );
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not apply changes."));
      }

      for await (const event of readNdjson(response)) {
        if (event.type === "started") {
          update({ journalId: event.journal_id });
        } else if (event.type === "result") {
          setState((current) => ({
            ...current,
            results: new Map(current.results).set(event.relative_path, event),
          }));
        } else if (event.type === "done") {
          update({ summary: event });
        }
      }
      update({ phase: "finished" });
    } catch (err) {
      update({
        phase: "finished",
        stopped: err.name === "AbortError",
        error: err.name === "AbortError" ? null : err.message,
      });
    }
  };

  const undo = async () => {
    update({ undoing: true });
    try {
      const response = await postJson("/undo", { journal_id: state.journalId });
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not undo."));
      }
      update({ phase: "undone", undoSummary: await response.json(), undoing: false });
    } catch (err) {
      update({ undoError: err.message, undoing: false });
    }
  };

  return {
    ...state,
    confirm: () => update({ phase: "confirming" }),
    cancel: () => setState(IDLE),
    run,
    stop: () => abortRef.current?.abort(),
    undo,
    locked: ["running", "finished", "undone"].includes(state.phase),
  };
}
