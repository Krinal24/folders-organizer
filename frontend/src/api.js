export const API_URL = "http://localhost:8000/api";

const TOKEN_HEADER = "X-TidyByte-Token";

// The backend makes a new session key each time it starts. Only this page
// can fetch it, and every other request must carry it.
let token = null;
let pending = null;

function fetchToken() {
  pending ??= fetch(`${API_URL}/session`)
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(await errorMessage(response, "Could not start a session."));
      }
      token = (await response.json()).token;
      return token;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

// For URLs that can't send headers, like <img src>. Thumbnails only show
// after a scan, so the key is there by then.
export function sessionToken() {
  return token;
}

export async function apiFetch(path, options = {}) {
  const send = (key) =>
    fetch(`${API_URL}${path}`, {
      ...options,
      headers: { ...options.headers, [TOKEN_HEADER]: key },
    });

  let response = await send(token ?? (await fetchToken()));
  if (response.status === 401) {
    // The backend restarted, so the key changed. Get the new one, once.
    response = await send(await fetchToken());
  }
  return response;
}

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
  return apiFetch(path, {
    method: "POST",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    body: JSON.stringify(body),
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
