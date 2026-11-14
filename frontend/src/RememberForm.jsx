import { useState } from "react";
import { errorMessage, postJson } from "./api.js";
import { plural } from "./format.js";

// Words that would match far too many files to be a useful rule.
const GENERIC = new Set([
  "copy", "doc", "document", "download", "file", "final", "image",
  "new", "scan", "untitled",
]);

// A starting point the user can edit: the part of the name most likely
// to recur in similar files.
function suggestPattern(name) {
  const stem = name.replace(/\.[^.]+$/, "");

  // Course-code style "21MAT21": keep the stable prefix, "21MAT".
  for (const token of stem.split(/[^A-Za-z0-9]+/)) {
    const code = token.match(/^(\d*[A-Za-z]{2,})\d+$/);
    if (code && /\d/.test(code[1])) return code[1];
  }

  const word = (stem.match(/[A-Za-z]{4,}/g) ?? []).find(
    (candidate) => !GENERIC.has(candidate.toLowerCase())
  );
  return word ?? stem.slice(0, 40);
}

export default function RememberForm({ item, name, countMatches, applyToMatches, onClose }) {
  const [pattern, setPattern] = useState(() => suggestPattern(name));
  const [status, setStatus] = useState({ phase: "editing" });

  const keep = item.action === "keep";
  const outcome = keep ? "stay where they are" : `go to ${item.destination}`;

  const save = async (event) => {
    event.preventDefault();
    setStatus({ phase: "saving" });
    try {
      const response = await postJson("/rules", {
        contains: pattern.trim(),
        action: keep ? "keep" : "move",
        destination: keep ? null : item.destination,
      });
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not save the rule."));
      }
      setStatus({ phase: "saved", matches: countMatches(pattern) });
    } catch (err) {
      setStatus({ phase: "editing", error: err.message });
    }
  };

  if (status.phase === "saved") {
    return (
      <div className="remember-form">
        <span>
          Saved. From now on, names containing “{pattern.trim()}” {outcome}.
        </span>
        {status.matches > 0 && (
          <button
            className="link-button"
            onClick={() => {
              applyToMatches(pattern);
              onClose();
            }}
          >
            Also apply to {plural(status.matches, "matching file")} in this plan
          </button>
        )}
        <button className="link-button" onClick={onClose}>
          Close
        </button>
      </div>
    );
  }

  return (
    <form className="remember-form" onSubmit={save}>
      <span>Names containing</span>
      <input
        autoFocus
        aria-label="Text the file name contains"
        value={pattern}
        onChange={(event) => setPattern(event.target.value)}
      />
      <span>always {outcome}.</span>
      <button
        type="submit"
        disabled={status.phase === "saving" || pattern.trim().length < 2}
      >
        {status.phase === "saving" ? "Saving…" : "Save rule"}
      </button>
      <button type="button" className="link-button" onClick={onClose}>
        Cancel
      </button>
      {status.error && <span className="remember-error">{status.error}</span>}
    </form>
  );
}
