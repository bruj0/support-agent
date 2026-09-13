// Initialise the Mermaid renderer after pymdownx has wrapped each
// ```mermaid``` fence as `<pre class="mermaid">…</pre>`. Without this,
// the page shows the raw mermaid source instead of an SVG.
//
// Runs after DOMContentLoaded so all `.mermaid` blocks are present.
// Uses `mermaid.run({ nodes })` (Mermaid v11 API) instead of the
// deprecated global `mermaid.init` / `mermaid.render` calls.
//
// Theme + htmlLabels + loose security match mkdocs-material's defaults
// and the user's test snippet in ~/.config/Code/User/History/.
(function () {
  function initMermaid() {
    if (typeof mermaid === "undefined") {
      // CDN still loading — try again on next tick.
      return setTimeout(initMermaid, 50);
    }
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: "default",
        flowchart: { htmlLabels: true },
        securityLevel: "loose",
      });
      var nodes = document.querySelectorAll("pre.mermaid");
      if (nodes.length > 0) {
        mermaid.run({ nodes: Array.from(nodes) }).catch(function (err) {
          console.error("mermaid.run failed:", err);
        });
      }
    } catch (err) {
      console.error("mermaid init failed:", err);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMermaid);
  } else {
    initMermaid();
  }
})();