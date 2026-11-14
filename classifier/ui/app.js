// API-001.4: the dashboard's script, plain JavaScript with no library and no build step
// (DOC-016.D1), served from the app's own origin so the page's CSP allows no inline script
// (API-001.D13).
// - Each element with data-fragment="<route>" is filled with a same-origin fetch() of that
//   server-rendered fragment on load (DOC-016.D3).
// - /api/events (API-001.D3) refreshes the fragments by group (API-001.D15): every status
//   frame refreshes data-group="refresh" (banner, grid, latest); "refresh-queue" (errors,
//   review queue) refreshes only when the run changes (its id or state), so a revealed
//   thumbnail there isn't re-blurred every 2 s.
// - Click-to-reveal (API-001.D8): toggles one thumbnail's data-blur in the browser only; it
//   is never sent or stored, so every page load starts blurred.
(function () {
  "use strict";

  var lastRun = null;

  // Only a path on this origin: one leading slash, never two, and no backslash.
  function sameOrigin(url) {
    return typeof url === "string" && /^\/(?![\/\\])[^\\]*$/.test(url);
  }

  // GET a fragment's HTML; null on any failure, so the element keeps what it shows.
  function getFragment(url) {
    if (!sameOrigin(url)) {
      return Promise.resolve(null);
    }
    return fetch(url, { credentials: "same-origin", redirect: "error", cache: "no-store" })
      .then(function (response) {
        return response.ok ? response.text() : null;
      })
      .catch(function () {
        return null;
      });
  }

  function load(el) {
    var seq = (Number(el.getAttribute("data-seq")) || 0) + 1;
    el.setAttribute("data-seq", String(seq));
    return getFragment(el.getAttribute("data-fragment")).then(function (html) {
      // A slower, older reply never overwrites a newer one.
      if (html !== null && el.getAttribute("data-seq") === String(seq)) {
        el.innerHTML = html;
      }
    });
  }

  function refresh(group) {
    var els = document.querySelectorAll('[data-fragment][data-group="' + group + '"]');
    Array.prototype.forEach.call(els, load);
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-fragment]"), load);

  var source = new EventSource("/api/events");
  source.addEventListener("status", function (event) {
    var key;
    try {
      var status = JSON.parse(event.data);
      key = status.run ? status.run.id + ":" + status.run.state : "none";
    } catch (err) {
      return;
    }
    refresh("refresh");
    if (lastRun !== null && key !== lastRun) {
      refresh("refresh-queue");
    }
    lastRun = key;
  });

  document.addEventListener("click", function (event) {
    var img = event.target;
    if (img instanceof HTMLImageElement && img.classList.contains("thumb")) {
      img.setAttribute("data-blur", img.getAttribute("data-blur") === "1" ? "0" : "1");
    }
  });
})();
