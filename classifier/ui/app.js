// API-001.4: the dashboard's few lines of script, served from the app's own origin so the
// page's CSP allows no inline script (API-001.D13).
// - /api/events (API-001.D3): every status frame refreshes the banner, grid and latest rows;
//   the review queue and errors refresh only when the run changes (its id or state), so a
//   revealed thumbnail there isn't re-blurred every 2 s.
// - Click-to-reveal (API-001.D8): toggles one thumbnail's data-blur in the browser only; it
//   is never sent or stored, so every page load starts blurred.
(function () {
  "use strict";

  var lastRun = null;

  function fire(name) {
    if (window.htmx) {
      window.htmx.trigger(document.body, name);
    }
  }

  var source = new EventSource("/api/events");
  source.addEventListener("status", function (event) {
    var key;
    try {
      var status = JSON.parse(event.data);
      key = status.run ? status.run.id + ":" + status.run.state : "none";
    } catch (err) {
      return;
    }
    fire("refresh");
    if (lastRun !== null && key !== lastRun) {
      fire("refresh-queue");
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
