(() => {
  const views = Array.from(document.querySelectorAll("[data-view]"));
  const phoneShell = document.querySelector(".phone-shell");
  const clock = document.querySelector("#clock");
  const callerName = document.querySelector("#caller-name");
  const callerAvatar = document.querySelector("#caller-avatar");
  const callKind = document.querySelector("#call-kind");

  function showView(name) {
    for (const view of views) {
      view.hidden = view.dataset.view !== name;
    }
    phoneShell.classList.toggle("phone-shell--ringing", name === "incoming-call");
  }

  function closeOverlay() {
    window.parent.postMessage({ __pluginOverlay: "drag", type: "close" }, "*");
  }

  function renderIncoming(payload) {
    const caller = String(payload?.caller || "").trim() || "未知联系人";
    const type = String(payload?.callType || "").toLowerCase() === "video" ? "video" : "voice";
    callerName.textContent = caller;
    callerAvatar.textContent = Array.from(caller)[0] || "?";
    callKind.textContent = type === "video" ? "视频来电" : "语音来电";
    showView("incoming-call");
  }

  function updateClock() {
    const now = new Date();
    clock.textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      hour12: false,
      minute: "2-digit",
    }).format(now);
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (
      event.source !== window.parent ||
      message?.__shinsekai !== "plugin-page" ||
      message.type !== "present"
    ) {
      return;
    }
    if (message.payload?.view === "incoming-call") {
      renderIncoming(message.payload);
    } else {
      showView("home");
    }
  });

  document.querySelector("#view-phone").addEventListener("click", () => showView("home"));
  document.querySelector("#dismiss-call").addEventListener("click", closeOverlay);
  document.querySelector("#close-overlay").addEventListener("click", closeOverlay);

  updateClock();
  window.setInterval(updateClock, 30_000);
  showView("home");
})();
