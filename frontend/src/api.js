export const API_URL = "http://localhost:8000/api";

export async function errorMessage(response, fallback) {
  try {
    const data = await response.json();
    return typeof data.detail === "string"
      ? data.detail
      : JSON.stringify(data.detail || fallback);
  } catch {
    return fallback;
  }
}

export function postJson(path, body, options = {}) {
  return fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...options,
  });
}

// Yields one parsed object per line of a newline-delimited JSON stream.
export async function* readNdjson(response) {
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
