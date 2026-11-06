// Reloads the page when the session's attendance changes (polls a tiny JSON endpoint).
(function () {
  var el = document.querySelector("[data-live-url]");
  if (!el) return;
  var url = el.getAttribute("data-live-url"), current = el.getAttribute("data-live-version");
  setInterval(function () {
    if (document.hidden) return;
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.v !== current) window.location.reload(); })
      .catch(function () {});
  }, 5000);
})();
