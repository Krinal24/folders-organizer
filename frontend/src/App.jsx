
import { useRef, useState } from "react";
import "./index.css";
import PlanView from "./PlanView.jsx";
import { formatBytes, plural } from "./format.js";
import { API_URL, readNdjson } from "./api.js";

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


function App() {
  const [folderPath, setFolderPath] = useState("");
  const [scanResult, setScanResult] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [readContents, setReadContents] = useState(true);

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
          read_contents: readContents,
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
            runId: Date.now(),
            path: event.path,
            suggestions: event.suggestions,
            destinations: event.destinations,
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
                  {plural(scanResult.total_items, "item")} &middot;{" "}
                  {formatBytes(scanResult.total_size)}
                </h2>
                <ProjectNote items={scanResult.items} />
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

              <label className="ai-toggle ai-toggle-sub">
                <input
                  type="checkbox"
                  checked={useAi && readContents}
                  onChange={(event) => setReadContents(event.target.checked)}
                  disabled={analyzing || !useAi}
                />
                Let the AI read the first lines of documents with unclear
                names, like “DOC-2022…pdf”
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
                    {analyzing && " so far"}
                  </span>
                </div>

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

                <PlanView
                  // A new analysis starts with a clean slate of edits.
                  key={analysisResult.runId}
                  suggestions={analysisResult.suggestions}
                  destinations={analysisResult.destinations}
                  path={analysisResult.path}
                  onRescan={scanFolder}
                />
              </section>
            )}
          </section>
        )}
      </section>
    </main>
  );
}

// Projects are counted as one item each; say how many files they hold.
function ProjectNote({ items }) {
  const projects = items.filter((item) => item.kind === "folder");
  if (projects.length === 0) return null;

  const files = projects.reduce((total, item) => total + (item.file_count || 0), 0);
  return (
    <p className="results-note">
      Includes {plural(projects.length, "code project")} with{" "}
      {files.toLocaleString()} files inside, kept together as one item each.
    </p>
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
