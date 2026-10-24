
import { useRef, useState } from "react";
import "./index.css";

const API_URL = "http://localhost:8000/api";

const CATEGORIES = [
  ["documents", "Documents"],
  ["images", "Images"],
  ["videos", "Videos"],
  ["audio", "Audio"],
  ["executables", "Executables"],
  ["archives", "Archives"],
  ["projects", "Projects"],
  ["unknown", "Unknown"],
];

const ACTION_ORDER = { delete: 0, move: 1, review: 2, keep: 3 };

const RULE_LABELS = {
  duplicate: "Duplicate",
  partial_download: "Leftover download",
  empty_file: "Empty file",
  old_installer: "Old installer",
  empty_folder: "Empty folder",
};

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

// Yields one parsed object per line of a newline-delimited JSON stream.
async function* readNdjson(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line);
    }
  }

  if (buffer.trim()) yield JSON.parse(buffer);
}

function sortSuggestions(suggestions) {
  return [...suggestions].sort(
    (a, b) =>
      ACTION_ORDER[a.action] - ACTION_ORDER[b.action] || b.size - a.size
  );
}

function App() {
  const [folderPath, setFolderPath] = useState("");
  const [scanResult, setScanResult] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [useAi, setUseAi] = useState(true);

  const [error, setError] = useState("");
  const [analysisError, setAnalysisError] = useState("");

  const abortRef = useRef(null);

  const scanFolder = async () => {
    if (!folderPath.trim()) {
      setError("Please enter a folder path.");
      return;
    }

    abortRef.current?.abort();
    setLoading(true);
    setError("");
    setAnalysisError("");
    setScanResult(null);
    setAnalysisResult(null);

    try {
      const response = await fetch(`${API_URL}/scan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: folderPath.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to scan folder.");
      }

      setScanResult(data);
    } catch (err) {
      setError(err.message || "Failed to connect to the backend.");
    } finally {
      setLoading(false);
    }
  };

  const analyzeFolder = async () => {
    if (!scanResult) {
      setAnalysisError("Scan a folder first.");
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setAnalyzing(true);
    setAnalysisError("");
    setAnalysisResult(null);

    try {
      const response = await fetch(`${API_URL}/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: scanResult.path,
          use_ai: useAi,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || "Analysis failed.")
        );
      }

      // Rule results arrive first; AI results trickle in one by one.
      for await (const event of readNdjson(response)) {
        if (event.type === "rules") {
          setAnalysisResult({
            path: event.path,
            suggestions: event.suggestions,
            aiPending: event.ai_pending,
            aiDone: 0,
            aiError: null,
            stopped: false,
          });
        } else if (event.type === "ai") {
          setAnalysisResult((current) => ({
            ...current,
            suggestions: [...current.suggestions, event.suggestion],
            aiDone: current.aiDone + 1,
          }));
        } else if (event.type === "error") {
          setAnalysisResult((current) => ({
            ...current,
            aiError: event.message,
          }));
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        setAnalysisResult((current) =>
          current && { ...current, stopped: true }
        );
      } else {
        setAnalysisError(
          err.message || "Could not complete the analysis."
        );
      }
    } finally {
      setAnalyzing(false);
    }
  };

  const stopAnalysis = () => abortRef.current?.abort();

  const reclaimableSize = (analysisResult?.suggestions ?? [])
    .filter((item) => item.action === "delete")
    .reduce((total, item) => total + item.size, 0);

  return (
    <main className="app">
      <section className="container">
        <header className="header">
          <p className="eyebrow">AI FILE ORGANIZER</p>
          <h1>TidyByte</h1>
          <p className="subtitle">
            Analyze and organize any folder on your computer.
          </p>
        </header>

        <section className="folder-section">
          <label htmlFor="folder-path">Folder to organize</label>

          <div className="path-row">
            <input
              id="folder-path"
              type="text"
              placeholder="C:\\Users\\YourName\\Downloads"
              value={folderPath}
              onChange={(event) => setFolderPath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !loading && !analyzing) {
                  scanFolder();
                }
              }}
            />

            <button
              className="primary-button"
              onClick={scanFolder}
              disabled={loading || analyzing}
            >
              {loading ? "Scanning..." : "Scan Folder"}
            </button>
          </div>

          {error && <p className="error">{error}</p>}
        </section>

        {scanResult && (
          <section className="results">
            <div className="results-header">
              <div>
                <p className="eyebrow">FOLDER ANALYSIS</p>
                <h2>
                  {scanResult.total_files} files &middot;{" "}
                  {formatBytes(scanResult.total_size)}
                </h2>
              </div>

              <p className="folder-location">{scanResult.path}</p>
            </div>

            <div className="stats-grid">
              {CATEGORIES.map(([key, label]) => (
                <StatCard
                  key={key}
                  value={scanResult.counts[key] || 0}
                  label={label}
                  size={scanResult.sizes[key] || 0}
                />
              ))}
            </div>

            {(scanResult.truncated || scanResult.skipped.length > 0) && (
              <div className="scan-warnings">
                {scanResult.truncated && (
                  <p>
                    This folder is very large, so the scan stopped after{" "}
                    {scanResult.total_items} items.
                  </p>
                )}

                {scanResult.skipped.length > 0 && (
                  <details>
                    <summary>
                      {scanResult.skipped.length} paths could not be scanned
                    </summary>
                    <ul>
                      {scanResult.skipped.map((item) => (
                        <li key={item.relative_path}>
                          {item.relative_path}: {item.reason}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}

            <div className="analyse-section">
              <h3>Ready to analyse?</h3>

              <p>
                Duplicates, leftover downloads, empty files and old
                installers are found instantly. The AI then suggests
                where everything else should go.
              </p>

              <label className="ai-toggle">
                <input
                  type="checkbox"
                  checked={useAi}
                  onChange={(event) => setUseAi(event.target.checked)}
                  disabled={analyzing}
                />
                Use AI for the remaining files (slower)
              </label>

              <button
                className="analyse-button"
                onClick={analyzeFolder}
                disabled={analyzing || loading}
              >
                {analyzing ? "Analyzing files..." : "Analyse Folder"}
              </button>

              {analyzing && analysisResult?.aiPending > 0 && (
                <div className="analysis-progress">
                  <p>
                    AI analyzed {analysisResult.aiDone} of{" "}
                    {analysisResult.aiPending} files. Results appear
                    below as they come in.
                  </p>
                  <progress
                    value={analysisResult.aiDone}
                    max={analysisResult.aiPending}
                  />
                  <button className="stop-button" onClick={stopAnalysis}>
                    Stop AI
                  </button>
                </div>
              )}

              {analysisError && (
                <p className="error analysis-error">
                  Analysis failed: {analysisError}
                </p>
              )}
            </div>

            {analysisResult && (
              <section className="plan-section">
                <div className="plan-header">
                  <div>
                    <p className="eyebrow">SUGGESTED PLAN</p>
                    <h2>Review your files</h2>
                  </div>

                  <span className="plan-count">
                    {analysisResult.suggestions.length} suggestions
                  </span>
                </div>

                <p className="plan-notice">
                  These are suggestions only. No files have been changed.
                  {reclaimableSize > 0 && (
                    <>
                      {" "}Deleting the suggested files would free{" "}
                      <strong>{formatBytes(reclaimableSize)}</strong>.
                    </>
                  )}
                </p>

                {analysisResult.aiError && (
                  <p className="scan-warnings">
                    The AI stopped working, so the remaining files have no
                    suggestions yet. ({analysisResult.aiError})
                  </p>
                )}

                {analysisResult.stopped && (
                  <p className="scan-warnings">
                    AI analysis stopped after {analysisResult.aiDone} of{" "}
                    {analysisResult.aiPending} files.
                  </p>
                )}

                <div className="plan-list">
                  {sortSuggestions(analysisResult.suggestions).map((item) => (
                    <article
                      className="plan-card"
                      key={item.relative_path}
                    >
                      <div className="plan-card-header">
                        <div className="file-details">
                          <h3>{item.relative_path}</h3>
                          <p>
                            <span className="source-tag">
                              {item.source === "rule"
                                ? RULE_LABELS[item.rule]
                                : "AI"}
                            </span>
                            {[item.category, item.subcategory]
                              .filter(Boolean)
                              .join(" / ")}
                            {item.kind === "file" &&
                              ` · ${formatBytes(item.size)}`}
                          </p>
                        </div>

                        <span
                          className={`action-badge action-${item.action}`}
                        >
                          {item.action}
                        </span>
                      </div>

                      <div className="plan-meta">
                        {item.action === "move" && (
                          <span>
                            <strong>Destination:</strong> {item.destination}
                          </span>
                        )}

                        {item.duplicate_of && (
                          <span>
                            <strong>Duplicate of:</strong>{" "}
                            {item.duplicate_of}
                          </span>
                        )}

                        <span>
                          <strong>Confidence:</strong>{" "}
                          {Math.round(item.confidence * 100)}%
                        </span>
                      </div>

                      <p className="plan-reason">{item.reason}</p>
                    </article>
                  ))}
                </div>
              </section>
            )}
          </section>
        )}
      </section>
    </main>
  );
}

function StatCard({ value, label, size }) {
  return (
    <div className="stat-card">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
      <span className="stat-size">{formatBytes(size)}</span>
    </div>
  );
}

export default App;
