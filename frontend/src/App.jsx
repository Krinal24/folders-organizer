import { useState } from "react";
import "./index.css";

const API_URL = "http://localhost:8000/api";

function App() {
  const [folderPath, setFolderPath] = useState("");
  const [scanResult, setScanResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const scanFolder = async () => {
    if (!folderPath.trim()) {
      setError("Please enter a folder path.");
      return;
    }

    setLoading(true);
    setError("");
    setScanResult(null);

    try {
      const response = await fetch(`${API_URL}/scan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          downloads_path: folderPath.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to scan folder.");
      }

      setScanResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
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
              placeholder="C:\Users\YourName\Downloads"
              value={folderPath}
              onChange={(event) => setFolderPath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  scanFolder();
                }
              }}
            />

            <button
              className="primary-button"
              onClick={scanFolder}
              disabled={loading}
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
                <h2>{scanResult.total} files found</h2>
              </div>

              <p className="folder-location">
                {scanResult.path}
              </p>
            </div>

            <div className="stats-grid">
              <StatCard
                value={scanResult.documents}
                label="Documents"
              />

              <StatCard
                value={scanResult.images}
                label="Images"
              />

              <StatCard
                value={scanResult.videos}
                label="Videos"
              />

              <StatCard
                value={scanResult.executables}
                label=".EXE"
              />

              <StatCard
                value={scanResult.archives}
                label="Archives"
              />

              <StatCard
                value={scanResult.unknown}
                label="Unknown"
              />
            </div>

            <div className="analyse-section">
              <h3>Ready for AI analysis?</h3>

              <p>
                DownloadMind will analyze the files and create a proposed
                organization plan.
              </p>

              <button className="analyse-button">
                Analyse Folder
              </button>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}


function StatCard({ value, label }) {
  return (
    <div className="stat-card">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}


export default App;