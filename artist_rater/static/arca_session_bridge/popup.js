const endpoint = "http://127.0.0.1:5001/api/arca-styles/browser-session/extension";
const connectButton = document.getElementById("connectSession");
const statusElement = document.getElementById("status");

function setStatus(message, state = "") {
  statusElement.textContent = message;
  statusElement.dataset.state = state;
}

function transferableCookies(cookies) {
  return cookies.map((cookie) => ({
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path,
    secure: cookie.secure,
    ...(cookie.expirationDate == null ? {} : { expirationDate: cookie.expirationDate }),
  }));
}

connectButton.addEventListener("click", async () => {
  connectButton.disabled = true;
  setStatus("Chrome 로그인 확인 중…");
  const controller = new AbortController();
  let timeout;
  try {
    let cookies;
    try {
      cookies = await chrome.cookies.getAll({ domain: "arca.live" });
    } catch (_error) {
      setStatus("Chrome 쿠키를 읽지 못했습니다. 확장의 아카라이브 사이트 접근 권한을 확인해 주세요.", "error");
      return;
    }
    if (!cookies.length) {
      setStatus("이 Chrome에서 아카라이브 로그인을 찾지 못했습니다.", "error");
      return;
    }
    timeout = setTimeout(() => controller.abort(), 20000);
    const response = await fetch(endpoint, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Arca-Session-Bridge": "1",
      },
      body: JSON.stringify({ cookies: transferableCookies(cookies) }),
    });
    const result = await response.json().catch((error) => {
      if (controller.signal.aborted) throw error;
      return {};
    });
    if (!response.ok || !result?.connected) {
      const message = typeof result?.error === "string" && result.error.trim()
        ? result.error
        : response.status === 404
          ? "로컬 앱에 Chrome 로그인 연결 기능이 없습니다. 앱을 업데이트한 뒤 다시 연결해 주세요."
          : `로컬 앱의 로그인 확인 응답이 올바르지 않습니다. (HTTP ${response.status})`;
      setStatus(message, "error");
      return;
    }
    setStatus("아카라이브 로그인을 연결했습니다.", "success");
  } catch (_error) {
    setStatus(controller.signal.aborted
      ? "로그인 확인 시간이 초과되었습니다. 앱의 연결 상태를 확인한 뒤 다시 시도해 주세요."
      : "로컬 앱에 연결하지 못했습니다. 앱이 실행 중인지 확인해 주세요.", "error");
  } finally {
    clearTimeout(timeout);
    connectButton.disabled = false;
  }
});
