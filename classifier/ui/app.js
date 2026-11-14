// API-001.4: the dashboard's script, plain JavaScript with no library and no build step
// (DOC-016.D1), served from the app's own origin so the page's CSP allows no inline script
// (API-001.D13).
// - Each element with data-fragment="<route>" is filled with a same-origin fetch() of that
//   server-rendered fragment on load (DOC-016.D3).
// - /api/events (API-001.D3) refreshes the fragments by group (API-001.D15): every status
//   frame refreshes data-group="refresh" (banner, grid, latest); "refresh-queue" (errors,
//   review queue) refreshes only when the run changes (its id or state), so a revealed
//   thumbnail there isn't re-blurred every 2 s.
// - A "more" row (tr.more[data-more], API-001.D14) loads the next page when it scrolls into
//   view (IntersectionObserver) or is clicked, and the rows replace it. No form or button.
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
        forEachMore(el, function (row) {
          observer.unobserve(row);
        });
        el.innerHTML = html;
        forEachMore(el, function (row) {
          observer.observe(row);
        });
      }
    });
  }

  // The "more" rows (API-001.D14): the next page loads when the row scrolls into view, or
  // on a click as the fallback, and its rows take the row's place. One load per row at a
  // time; a failed load leaves the row, so a click retries.
  var observer =
    "IntersectionObserver" in window
      ? new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              loadMore(entry.target);
            }
          });
        })
      : null;

  function forEachMore(root, fn) {
    if (observer) {
      Array.prototype.forEach.call(root.querySelectorAll("tr.more[data-more]"), fn);
    }
  }

  function loadMore(row) {
    if (row.getAttribute("data-loading") === "1") {
      return;
    }
    row.setAttribute("data-loading", "1");
    getFragment(row.getAttribute("data-more")).then(function (html) {
      if (html === null || !row.parentNode) {
        row.removeAttribute("data-loading");
        return;
      }
      if (observer) {
        observer.unobserve(row);
      }
      var parent = row.parentNode;
      var holder = document.createElement("template");
      holder.innerHTML = "<table><tbody>" + html + "</tbody></table>";
      var rows = holder.content.querySelectorAll("tbody > tr");
      Array.prototype.forEach.call(rows, function (tr) {
        parent.insertBefore(tr, row);
      });
      parent.removeChild(row);
      forEachMore(parent, function (next) {
        observer.observe(next);
      });
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
    var target = event.target;
    if (target instanceof HTMLImageElement && target.classList.contains("thumb")) {
      target.setAttribute("data-blur", target.getAttribute("data-blur") === "1" ? "0" : "1");
      return;
    }
    var more = target instanceof Element ? target.closest("tr.more[data-more]") : null;
    if (more) {
      event.preventDefault(); // the link's "#" never navigates
      loadMore(more);
    }
  });
})();
