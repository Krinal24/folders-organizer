
import { useState } from "react";
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

function App() {
  const [folderPath, setFolderPath] = useState("");
  const [scanResult, setScanResult] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);

  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const [error, setError] = useState("");
  const [analysisError, setAnalysisError] = useState("");

  const scanFolder = async () => {
    if (!folderPath.trim()) {
      setError("Please enter a folder path.");
      return;
    }

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
    if (!scanResult?.items?.length) {
      setAnalysisError("Scan a folder containing files first.");
      return;
    }

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
          files: scanResult.items,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || "AI analysis failed.")
        );
      }

      setAnalysisResult(data);
    } catch (err) {
      setAnalysisError(
        err.message || "Could not complete AI analysis."
      );
    } finally {
      setAnalyzing(false);
    }
  };

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
              <h3>Ready for AI analysis?</h3>

              <p>
                DownloadMind will examine file metadata and propose
                an organization plan for you to review.
              </p>

              <button
                className="analyse-button"
                onClick={analyzeFolder}
                disabled={analyzing || loading}
              >
                {analyzing ? "Analyzing files..." : "Analyse Folder"}
              </button>

              {analyzing && (
                <p className="analysis-progress">
                  Gemma is analyzing your files. This may take a while
                  for larger folders.
                </p>
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
                    <p className="eyebrow">AI-GENERATED PLAN</p>
                    <h2>Review your files</h2>
                  </div>

                  <span className="plan-count">
                    {analysisResult.analyses.length} analyzed
                  </span>
                </div>

                <p className="plan-notice">
                  These are suggestions only. No files have been changed.
                </p>

                <div className="plan-list">
                  {analysisResult.analyses.map((item) => (
                    <article
                      className="plan-card"
                      key={item.relative_path}
                    >
                      <div className="plan-card-header">
                        <div className="file-details">
                          <h3>{item.relative_path}</h3>
                          <p>
                            {item.category} / {item.subcategory}
                          </p>
                        </div>

                        <span
                          className={`action-badge action-${item.action}`}
                        >
                          {item.action}
                        </span>
                      </div>

                      <div className="plan-meta">
                        <span>
                          <strong>Destination:</strong>{" "}
                          {item.destination || "No destination proposed"}
                        </span>

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
