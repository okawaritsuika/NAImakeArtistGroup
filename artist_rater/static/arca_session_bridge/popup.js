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
    const cookies = await chrome.cookies.getAll({ domain: "arca.live" });
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
    if (!response.ok || !result.connected) {
      setStatus("로그인 연결을 확인하지 못했습니다.", "error");
      return;
    }
    setStatus("아카라이브 로그인을 연결했습니다.", "success");
  } catch (_error) {
    setStatus("로컬 앱에 연결하지 못했습니다. 앱이 실행 중인지 확인해 주세요.", "error");
  } finally {
    connectButton.disabled = false;
  }
});
