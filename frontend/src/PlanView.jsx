import { useState } from "react";
import { formatBytes, plural } from "./format.js";

const DELETE_GROUPS = {
  duplicate: ["Duplicates", "Identical copies of another file in this folder"],
  old_installer: ["Old installers", "Setup files for apps you have probably installed"],
  partial_download: ["Leftover downloads", "Unfinished downloads and temporary files"],
  empty_file: ["Empty files", "Files with no content (0 bytes)"],
  empty_folder: ["Empty folders", "Folders with nothing inside"],
  user: ["Delete (your choice)", "Files you chose to delete"],
};

const ACTION_FILTERS = [
  ["all", "All"],
  ["delete", "Delete"],
  ["move", "Move"],
  ["review", "Review"],
];

// Rows shown per group before "Show more".
const PAGE_SIZE = 25;

const KEEP = "__keep";
const DELETE = "__delete";
const NEW_FOLDER = "__new";

function overrideFor(choice) {
  if (choice === KEEP) return { action: "keep", destination: null };
  if (choice === DELETE) return { action: "delete", destination: null, rule: "user" };
  return { action: "move", destination: choice };
}

function groupKey(item) {
  if (item.action === "delete") return `delete:${item.rule}`;
  if (item.action === "move") return `move:${item.destination}`;
  return item.action;
}

function describeGroup(key, items) {
  const [action, detail] = key.split(":");

  if (action === "delete") {
    const [title, description] = DELETE_GROUPS[detail] ?? ["Delete", ""];
    return { action, title, description };
  }
  if (action === "move") {
    const byType = items.every(
      (item) => item.rule === "file_type" && !item.overridden
    );
    return {
      action,
      title: `Move to ${detail}`,
      description: byType ? "Grouped by file type" : "",
    };
  }
  if (action === "review") {
    return {
      action,
      title: "Needs your review",
      description: "Not enough to go on. Pick a folder or keep them.",
    };
  }
  return {
    action,
    title: "Keep where they are",
    description: "These won't be moved",
  };
}

const ACTION_RANK = { delete: 0, move: 1, review: 2, keep: 3 };

function buildGroups(suggestions) {
  const groups = new Map();

  for (const item of suggestions) {
    const key = groupKey(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }

  return [...groups.entries()]
    .map(([key, items]) => ({
      key,
      items: [...items].sort((a, b) => b.size - a.size),
      size: items.reduce((total, item) => total + item.size, 0),
      ...describeGroup(key, items),
    }))
    .sort(
      (a, b) =>
        ACTION_RANK[a.action] - ACTION_RANK[b.action] ||
        (a.action === "delete" ? b.size - a.size : b.items.length - a.items.length)
    );
}

function totals(suggestions, action) {
  const items = suggestions.filter((item) => item.action === action);
  return {
    count: items.length,
    size: items.reduce((total, item) => total + item.size, 0),
    folders: new Set(items.map((item) => item.destination)).size,
  };
}

// Mirrors the backend rule: a destination must stay inside the scanned folder.
function cleanFolderName(value) {
  const folder = value.trim().replaceAll("\\", "/").replace(/\/+$/, "");
  const parts = folder.split("/");

  if (
    !folder ||
    folder.startsWith("/") ||
    folder.includes(":") ||
    parts.some((part) => part === ".." || part === "." || !part.trim())
  ) {
    return null;
  }
  return folder;
}

export default function PlanView({ suggestions, destinations = [] }) {
  const [filter, setFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [openGroups, setOpenGroups] = useState(() => new Set());
  // relative_path -> { action, destination } chosen by the user.
  const [overrides, setOverrides] = useState(() => new Map());
  const [customFolders, setCustomFolders] = useState([]);

  const effective = suggestions.map((item) => {
    const override = overrides.get(item.relative_path);
    return override ? { ...item, ...override, overridden: true } : item;
  });

  const folderOptions = [
    ...new Set([
      ...destinations,
      ...customFolders,
      ...effective.map((item) => item.destination).filter(Boolean),
    ]),
  ].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));

  const query = filter.trim().toLowerCase();
  const visible = effective.filter(
    (item) =>
      (actionFilter === "all" || item.action === actionFilter) &&
      (!query || item.relative_path.toLowerCase().includes(query))
  );
  const groups = buildGroups(visible);

  const toDelete = totals(effective, "delete");
  const toMove = totals(effective, "move");
  const toReview = totals(effective, "review");
  const changedCount = overrides.size;

  const toggleGroup = (key) =>
    setOpenGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const applyChoice = (items, choice) => {
    const override = overrideFor(choice);
    const isFolder = choice !== KEEP && choice !== DELETE;

    if (isFolder && !folderOptions.includes(choice)) {
      setCustomFolders((current) => [...current, choice]);
    }

    setOverrides((current) => {
      const next = new Map(current);
      for (const item of items) {
        const original = suggestions.find(
          (s) => s.relative_path === item.relative_path
        );
        const unchanged =
          original.action === override.action &&
          (original.destination ?? null) === override.destination;
        if (unchanged) next.delete(item.relative_path);
        else next.set(item.relative_path, override);
      }
      return next;
    });

    // Open the group the items landed in, so the change is easy to see.
    setOpenGroups((current) =>
      new Set(current).add(groupKey({ ...items[0], ...override }))
    );
  };

  const undo = (item) =>
    setOverrides((current) => {
      const next = new Map(current);
      next.delete(item.relative_path);
      return next;
    });

  const allOpen = groups.length > 0 && groups.every((g) => openGroups.has(g.key));

  return (
    <div className="plan-view">
      <div className="plan-summary">
        <SummaryTile
          action="delete"
          active={actionFilter === "delete"}
          onClick={() => setActionFilter(actionFilter === "delete" ? "all" : "delete")}
          value={plural(toDelete.count, "file")}
          label={`to delete · frees ${formatBytes(toDelete.size)}`}
        />
        <SummaryTile
          action="move"
          active={actionFilter === "move"}
          onClick={() => setActionFilter(actionFilter === "move" ? "all" : "move")}
          value={plural(toMove.count, "file")}
          label={`to move into ${plural(toMove.folders, "folder")}`}
        />
        <SummaryTile
          action="review"
          active={actionFilter === "review"}
          onClick={() => setActionFilter(actionFilter === "review" ? "all" : "review")}
          value={plural(toReview.count, "file")}
          label="need your review"
        />
      </div>

      <div className="plan-toolbar">
        <input
          type="search"
          placeholder="Filter by file name…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />

        <div className="action-filters" role="tablist">
          {ACTION_FILTERS.map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={actionFilter === value}
              className={actionFilter === value ? "active" : ""}
              onClick={() => setActionFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <button
          className="link-button"
          onClick={() =>
            setOpenGroups(allOpen ? new Set() : new Set(groups.map((g) => g.key)))
          }
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>

      {changedCount > 0 && (
        <p className="changes-note">
          You changed {plural(changedCount, "item")}.{" "}
          <button className="link-button" onClick={() => setOverrides(new Map())}>
            Undo all changes
          </button>
        </p>
      )}

      {groups.length === 0 && (
        <p className="plan-empty">No suggestions match this filter.</p>
      )}

      <div className="plan-groups">
        {groups.map((group) => (
          <PlanGroup
            key={group.key}
            group={group}
            // A search opens every matching group.
            open={Boolean(query) || openGroups.has(group.key)}
            onToggle={() => toggleGroup(group.key)}
            folderOptions={folderOptions}
            onChoose={applyChoice}
            onUndo={undo}
          />
        ))}
      </div>
    </div>
  );
}

function SummaryTile({ action, active, onClick, value, label }) {
  return (
    <button
      className={`summary-tile summary-${action} ${active ? "active" : ""}`}
      onClick={onClick}
      aria-pressed={active}
    >
      <span className="summary-value">{value}</span>
      <span className="summary-label">{label}</span>
    </button>
  );
}

function PlanGroup({ group, open, onToggle, folderOptions, onChoose, onUndo }) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const remaining = group.items.length - shown;
  const currentFolder = group.action === "move" ? group.items[0].destination : null;

  return (
    <section className={`plan-group group-${group.action}`}>
      <div className="group-header">
        <button className="group-toggle" onClick={onToggle} aria-expanded={open}>
          <span className={`chevron ${open ? "open" : ""}`} aria-hidden="true">
            ›
          </span>
          <span className="group-title">
            <strong>{group.title}</strong>
            {group.description && <span>{group.description}</span>}
          </span>
          <span className="group-stats">
            {plural(group.items.length, "item")}
            {group.size > 0 && ` · ${formatBytes(group.size)}`}
          </span>
        </button>

        <ChangeMenu
          label={group.items.length > 1 ? "Change all…" : "Change…"}
          folderOptions={folderOptions}
          currentFolder={currentFolder}
          action={group.action}
          onChoose={(choice) => onChoose(group.items, choice)}
        />
      </div>

      {open && (
        <ul className="group-rows">
          {group.items.slice(0, shown).map((item) => (
            <PlanRow
              key={item.relative_path}
              item={item}
              folderOptions={folderOptions}
              onChoose={(choice) => onChoose([item], choice)}
              onUndo={() => onUndo(item)}
            />
          ))}
          {remaining > 0 && (
            <li className="show-more">
              <button
                className="link-button"
                onClick={() => setShown(shown + PAGE_SIZE * 4)}
              >
                Show {Math.min(remaining, PAGE_SIZE * 4)} more of {remaining}
              </button>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

function PlanRow({ item, folderOptions, onChoose, onUndo }) {
  const separator = Math.max(
    item.relative_path.lastIndexOf("\\"),
    item.relative_path.lastIndexOf("/")
  );
  const name = item.relative_path.slice(separator + 1);
  const folder = separator > 0 ? item.relative_path.slice(0, separator) : "";

  // The group header already explains file-type moves and empty items.
  const detail = item.overridden
    ? ""
    : item.duplicate_of
      ? `Copy of ${item.duplicate_of}`
      : ["file_type", "empty_file", "empty_folder"].includes(item.rule)
        ? ""
        : item.reason;

  return (
    <li className="plan-row">
      <div className="row-main">
        <span className="row-name" title={item.relative_path}>
          {item.kind === "folder" ? "📁 " : ""}
          {name}
        </span>
        {(folder || detail || item.overridden) && (
          <span className="row-detail">
            {folder && (
              <span className="row-folder">
                in {folder}
                {(detail || item.overridden) && " · "}
              </span>
            )}
            {item.overridden ? (
              <span className="row-changed">
                Changed by you{" "}
                <button className="link-button" onClick={onUndo}>
                  Undo
                </button>
              </span>
            ) : (
              detail
            )}
          </span>
        )}
      </div>

      <span className="row-meta">
        {item.kind === "file" && formatBytes(item.size)}
        {item.source === "ai" && !item.overridden && (
          <span
            className="row-confidence"
            title={`AI confidence ${Math.round(item.confidence * 100)}%`}
          >
            {Math.round(item.confidence * 100)}%
          </span>
        )}
      </span>

      <ChangeMenu
        label="Change…"
        folderOptions={folderOptions}
        currentFolder={item.action === "move" ? item.destination : null}
        action={item.action}
        onChoose={onChoose}
      />
    </li>
  );
}

function ChangeMenu({ label, folderOptions, currentFolder, action, onChoose }) {
  const [creating, setCreating] = useState(false);
  const [newFolder, setNewFolder] = useState("");
  const [invalid, setInvalid] = useState(false);

  if (creating) {
    const submit = (event) => {
      event.preventDefault();
      const folder = cleanFolderName(newFolder);
      if (!folder) {
        setInvalid(true);
        return;
      }
      onChoose(folder);
      setCreating(false);
      setNewFolder("");
      setInvalid(false);
    };

    return (
      <form className="new-folder" onSubmit={submit}>
        <input
          autoFocus
          aria-label="New folder name"
          aria-invalid={invalid}
          placeholder="e.g. Documents/Taxes"
          value={newFolder}
          onChange={(event) => {
            setNewFolder(event.target.value);
            setInvalid(false);
          }}
          onKeyDown={(event) => event.key === "Escape" && setCreating(false)}
        />
        <button type="submit">Add</button>
        <button type="button" className="link-button" onClick={() => setCreating(false)}>
          Cancel
        </button>
        {invalid && (
          <span className="new-folder-error">
            Use a folder inside this one, like Documents/Taxes
          </span>
        )}
      </form>
    );
  }

  return (
    <select
      className="move-menu"
      aria-label={label}
      value=""
      onChange={(event) => {
        const choice = event.target.value;
        if (choice === NEW_FOLDER) setCreating(true);
        else if (choice) onChoose(choice);
      }}
    >
      <option value="">{label}</option>
      <optgroup label="Move to folder">
        {folderOptions
          .filter((folder) => folder !== currentFolder)
          .map((folder) => (
            <option key={folder} value={folder}>
              {folder}
            </option>
          ))}
        <option value={NEW_FOLDER}>+ New folder…</option>
      </optgroup>
      <optgroup label="Or">
        {action !== "keep" && <option value={KEEP}>Keep where it is</option>}
        {action !== "delete" && <option value={DELETE}>Delete</option>}
      </optgroup>
    </select>
  );
}
