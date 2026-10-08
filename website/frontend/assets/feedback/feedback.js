// Feedback capture for the bug control in the left rail.
//
// The script loads with the application. It keeps the newest log entries in memory:
// console info, warnings and errors, uncaught errors, rejected promises, and failed
// requests. It holds no entry from before it loaded.
//
// window.hooverFeedback.capture() copies the DOM, draws a PNG image of the tab from the
// DOM with html-to-image, and keeps both for send(). It returns the image, the sizes,
// the log entries, the debug context and notes about parts that it cannot draw.
// window.hooverFeedback.send(fields) posts the report to /_feedback/submit.
(function () {
  "use strict";

  var MAX_ENTRIES = 500;
  var MAX_MESSAGE_CHARS = 1000;
  var entries = [];
  var captured = null;

  // Values after these names are replaced, so a log entry does not keep a credential.
  var SECRET = /((?:password|passwd|secret|token|api[_-]?key|session|cookie|authorization)["']?\s*[:=]\s*["']?)[^"'&\s,;]+/gi;
  var BEARER = /(bearer\s+)[A-Za-z0-9._~+\/-]+=*/gi;

  function scrub(text) {
    return String(text).replace(SECRET, "$1[removed]").replace(BEARER, "$1[removed]");
  }

  function describe(value) {
    if (value instanceof Error) return value.name + ": " + value.message;
    if (typeof Event !== "undefined" && value instanceof Event) {
      var t = value.target;
      var what = t && t.tagName ? t.tagName.toLowerCase() + (t.src ? " " + String(t.src).slice(0, 120) : "") : "the page";
      return "a " + value.type + " event on " + what;
    }
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value);
    } catch (e) {
      return String(value);
    }
  }

  // The application logger styles its console lines with "%c" markers. Each marker
  // takes one CSS argument, so the markers and their arguments are removed.
  function unstyle(parts) {
    parts = Array.prototype.slice.call(parts);
    if (typeof parts[0] !== "string" || parts[0].indexOf("%c") < 0) return parts;
    var markers = parts[0].split("%c").length - 1;
    return [parts[0].split("%c").join("")].concat(parts.slice(1 + markers));
  }

  function record(level, source, parts) {
    var message = scrub(unstyle(parts).map(describe).join(" "));
    if (message.length > MAX_MESSAGE_CHARS) message = message.slice(0, MAX_MESSAGE_CHARS) + "…";
    entries.push({ time: new Date().toISOString(), level: level, source: source, message: message });
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
  }

  [["log", "info"], ["info", "info"], ["warn", "warning"], ["error", "error"]].forEach(function (pair) {
    var original = console[pair[0]];
    if (typeof original !== "function") return;
    console[pair[0]] = function () {
      try {
        record(pair[1], "console", arguments);
      } catch (e) {
        // A log entry that cannot be recorded must not stop the console call.
      }
      return original.apply(console, arguments);
    };
  });

  window.addEventListener("error", function (event) {
    var where = event.filename ? " (" + event.filename + ":" + event.lineno + ")" : "";
    record("error", "uncaught", [(event.error || event.message) + where]);
  });
  window.addEventListener("unhandledrejection", function (event) {
    record("error", "rejection", [event.reason]);
  });

  // Only the path of a request is recorded. The query string can hold values that the
  // person typed.
  function requestPath(input) {
    try {
      var url = new URL(typeof input === "string" ? input : input.url, location.href);
      return url.origin === location.origin ? url.pathname : url.origin + url.pathname;
    } catch (e) {
      return "(unknown address)";
    }
  }

  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = function (input, init) {
      var method = (init && init.method) || (input && input.method) || "GET";
      var path = requestPath(input);
      return originalFetch.apply(this, arguments).then(
        function (response) {
          if (!response.ok) record("error", "request", [method + " " + path + " returned " + response.status]);
          return response;
        },
        function (error) {
          record("error", "request", [method + " " + path + " failed: " + describe(error)]);
          throw error;
        }
      );
    };
  }

  // crypto.randomUUID exists only in a secure context, and a local stack can serve the
  // site over plain HTTP.
  function newReportId() {
    var b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    var h = Array.prototype.map.call(b, function (x) { return (x + 0x100).toString(16).slice(1); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }

  function debugContext() {
    var nav = navigator;
    return {
      url: location.href,
      path: location.pathname,
      hash: location.hash,
      title: document.title,
      captured_at: new Date().toISOString(),
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      viewport: window.innerWidth + " x " + window.innerHeight,
      screen: screen.width + " x " + screen.height,
      device_pixel_ratio: window.devicePixelRatio,
      user_agent: nav.userAgent,
      language: nav.language,
      languages: (nav.languages || []).join(", "),
      platform: nav.platform,
      online: nav.onLine,
      hardware_concurrency: nav.hardwareConcurrency,
      device_memory_gb: nav.deviceMemory,
      heading: (document.querySelector("#x-page-container h1") || {}).textContent || "",
      active_element: document.activeElement ? document.activeElement.tagName.toLowerCase() + (document.activeElement.id ? "#" + document.activeElement.id : "") : "",
      scroll_positions: Array.prototype.filter
        .call(document.querySelectorAll("[id]"), function (e) { return e.scrollTop > 0; })
        .slice(0, 20)
        .map(function (e) { return "#" + e.id + " " + Math.round(e.scrollTop); }),
    };
  }

  // Parts of the page that the drawn image cannot show as the screen shows them.
  function captureNotes() {
    var notes = [];
    var frames = document.querySelectorAll("iframe");
    if (frames.length) {
      notes.push(frames.length + " frame(s) on the page. The image shows only frame content from this site.");
    }
    var tainted = 0;
    document.querySelectorAll("canvas").forEach(function (c) {
      try {
        c.toDataURL();
      } catch (e) {
        tainted += 1;
      }
    });
    if (tainted) notes.push(tainted + " canvas(es) hold content from another site and show empty in the image.");
    var shadowHosts = Array.prototype.filter.call(document.querySelectorAll("*"), function (e) { return !!e.shadowRoot; });
    if (shadowHosts.length) {
      notes.push(shadowHosts.length + " element(s) keep content in a shadow root. The image can show them empty.");
    }
    return notes;
  }

  function base64Bytes(b64) {
    var padding = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
    return Math.floor((b64.length * 3) / 4) - padding;
  }

  async function capture() {
    var notes = captureNotes();
    var dom = "";
    try {
      dom = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
    } catch (e) {
      notes.push("The DOM copy failed: " + describe(e));
    }
    var pngDataUrl = "";
    if (window.htmlToImage) {
      try {
        pngDataUrl = await window.htmlToImage.toPng(document.body, {
          width: window.innerWidth,
          height: window.innerHeight,
          pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
          backgroundColor: "#ffffff",
          // An image that cannot be fetched is drawn as this empty image, so one
          // failed image does not stop the whole drawing.
          imagePlaceholder: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
          filter: function (node) { return !(node.id && node.id === "x-feedback-overlay"); },
        });
      } catch (e) {
        notes.push("The page image failed: " + describe(e));
      }
    } else {
      notes.push("The image library did not load, so the report has no page image.");
    }
    var pngBase64 = pngDataUrl.slice(pngDataUrl.indexOf(",") + 1);
    captured = {
      report_id: newReportId(),
      png_base64: pngDataUrl ? pngBase64 : "",
      dom: dom,
      context: debugContext(),
      notes: notes,
      logs: entries.slice(),
    };
    return {
      report_id: captured.report_id,
      png_data_url: pngDataUrl,
      png_bytes: pngDataUrl ? base64Bytes(pngBase64) : 0,
      dom_bytes: new Blob([dom]).size,
      context: captured.context,
      notes: notes,
      logs: captured.logs,
    };
  }

  async function send(fields) {
    if (!captured) return { ok: false, status: 0, message: "Nothing was captured." };
    var body = {
      report_id: captured.report_id,
      kind: fields.kind,
      title: fields.title,
      description: fields.description,
      page_url: captured.context.url,
      context_json: JSON.stringify({ context: captured.context, notes: captured.notes, logs: captured.logs }),
      screenshot_png_base64: captured.png_base64,
      dom_html: captured.dom,
    };
    try {
      var response = await originalFetch("/_feedback/submit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      var text = await response.text();
      return { ok: response.ok, status: response.status, message: response.ok ? "" : text };
    } catch (e) {
      return { ok: false, status: 0, message: describe(e) };
    }
  }

  function discard() {
    captured = null;
  }

  window.hooverFeedback = { capture: capture, send: send, discard: discard };
})();
