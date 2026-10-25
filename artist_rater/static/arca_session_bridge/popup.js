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
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Arca-Session-Bridge": "1",
      },
      body: JSON.stringify({ cookies: transferableCookies(cookies) }),
    });
    const result = await response.json().catch(() => ({}));
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
    setStatus("로컬 앱에 연결하지 못했습니다. 앱이 실행 중인지 확인해 주세요.", "error");
  } finally {
    connectButton.disabled = false;
  }
});
