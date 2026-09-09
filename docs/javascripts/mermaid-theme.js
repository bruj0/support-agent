// Theme-aware Mermaid colors. Material integrates Mermaid out of the box but
// doesn't switch the Mermaid palette when the user toggles dark mode, so
// light-mode diagrams end up with light-grey fills that vanish against the
// Material background. We (1) initialize Mermaid with the correct palette for
// the current scheme and (2) re-run it whenever Material flips the scheme.
//
// `theme: "base"` lets us inject arbitrary themeVariables. We override the
// keys Mermaid uses internally so the rendered SVG is generated with the
// right colors from the start -- no inline-style fight with the CSS that the
// SVG ships with.

(function () {
  "use strict";

  var LIGHT = {
    theme: "base",
    themeVariables: {
      // background + node fill
      background: "#ffffff",
      primaryColor: "#e0e7ff",
      primaryBorderColor: "#1f2937",
      primaryTextColor: "#0f172a",
      // secondary nodes (alt fill)
      secondaryColor: "#f1f5f9",
      secondaryBorderColor: "#475569",
      secondaryTextColor: "#0f172a",
      // tertiary
      tertiaryColor: "#fef3c7",
      tertiaryBorderColor: "#92400e",
      tertiaryTextColor: "#1a1a1a",
      // edges + arrows + text on edges
      lineColor: "#334155",
      textColor: "#0f172a",
      // main label box
      mainBkg: "#ffffff",
      nodeBorder: "#1f2937",
      clusterBkg: "#f1f5f9",
      clusterBorder: "#64748b",
      // sequence diagrams
      actorBkg: "#e0e7ff",
      actorBorder: "#1f2937",
      actorTextColor: "#0f172a",
      actorLineColor: "#334155",
      signalColor: "#334155",
      signalTextColor: "#0f172a",
      labelBoxBkgColor: "#fef3c7",
      labelBoxBorderColor: "#92400e",
      labelTextColor: "#1a1a1a",
      loopTextColor: "#1a1a1a",
      noteBkgColor: "#f1f5f9",
      noteBorderColor: "#64748b",
      noteTextColor: "#0f172a",
      // class / state diagrams
      classText: "#0f172a",
      fillType0: "#e0e7ff",
      fillType1: "#fef3c7",
      fillType2: "#dcfce7",
      fillType3: "#fce7f3",
      fillType4: "#cffafe",
      fillType5: "#fee2e2",
      fillType6: "#f3e8ff",
      fillType7: "#ffedd5",
      // gitGraph
      git0: "#6366f1",
      git1: "#f59e0b",
      git2: "#10b981",
      git3: "#ec4899",
      git4: "#06b6d4",
      git5: "#ef4444",
      git6: "#a855f7",
      git7: "#f97316",
      gitBranchLabel0: "#ffffff",
      gitBranchLabel1: "#ffffff",
      gitBranchLabel2: "#ffffff",
      gitBranchLabel3: "#ffffff",
      gitBranchLabel4: "#ffffff",
      gitBranchLabel5: "#ffffff",
      gitBranchLabel6: "#ffffff",
      gitBranchLabel7: "#ffffff",
      commitLabelColor: "#ffffff",
      commitLabelBackground: "#1f2937",
      commitLabelFontSize: "12px",
      tagLabelColor: "#ffffff",
      tagLabelBackground: "#475569",
      tagLabelBorder: "#475569",
      tagLabelFontSize: "11px",
    },
    flowchart: { htmlLabels: true, curve: "basis" },
    sequence: { showSequenceNumbers: false },
    securityLevel: "loose",
  };

  var DARK = {
    theme: "base",
    themeVariables: {
      background: "#0f172a",
      primaryColor: "#1e293b",
      primaryBorderColor: "#94a3b8",
      primaryTextColor: "#f1f5f9",
      secondaryColor: "#0b1220",
      secondaryBorderColor: "#64748b",
      secondaryTextColor: "#f1f5f9",
      tertiaryColor: "#3f2a14",
      tertiaryBorderColor: "#fbbf24",
      tertiaryTextColor: "#fef3c7",
      lineColor: "#cbd5e1",
      textColor: "#f1f5f9",
      mainBkg: "#1e293b",
      nodeBorder: "#94a3b8",
      clusterBkg: "#0b1220",
      clusterBorder: "#64748b",
      actorBkg: "#1e293b",
      actorBorder: "#94a3b8",
      actorTextColor: "#f1f5f9",
      actorLineColor: "#cbd5e1",
      signalColor: "#cbd5e1",
      signalTextColor: "#f1f5f9",
      labelBoxBkgColor: "#3f2a14",
      labelBoxBorderColor: "#fbbf24",
      labelTextColor: "#fef3c7",
      loopTextColor: "#fef3c7",
      noteBkgColor: "#0b1220",
      noteBorderColor: "#64748b",
      noteTextColor: "#f1f5f9",
      classText: "#f1f5f9",
      fillType0: "#312e81",
      fillType1: "#78350f",
      fillType2: "#064e3b",
      fillType3: "#831843",
      fillType4: "#155e75",
      fillType5: "#7f1d1d",
      fillType6: "#581c87",
      fillType7: "#7c2d12",
      git0: "#818cf8",
      git1: "#fbbf24",
      git2: "#34d399",
      git3: "#f472b6",
      git4: "#22d3ee",
      git5: "#f87171",
      git6: "#c084fc",
      git7: "#fb923c",
      gitBranchLabel0: "#0f172a",
      gitBranchLabel1: "#0f172a",
      gitBranchLabel2: "#0f172a",
      gitBranchLabel3: "#0f172a",
      gitBranchLabel4: "#0f172a",
      gitBranchLabel5: "#0f172a",
      gitBranchLabel6: "#0f172a",
      gitBranchLabel7: "#0f172a",
      commitLabelColor: "#0f172a",
      commitLabelBackground: "#cbd5e1",
      commitLabelFontSize: "12px",
      tagLabelColor: "#0f172a",
      tagLabelBackground: "#cbd5e1",
      tagLabelBorder: "#cbd5e1",
      tagLabelFontSize: "11px",
    },
    flowchart: { htmlLabels: true, curve: "basis" },
    sequence: { showSequenceNumbers: false },
    securityLevel: "loose",
  };

  function currentPalette() {
    var scheme = document.querySelector("[data-md-color-scheme]");
    return scheme && scheme.getAttribute("data-md-color-scheme") === "slate"
      ? DARK
      : LIGHT;
  }

  function rerender() {
    if (typeof window.mermaid === "undefined") return;
    var nodes = document.querySelectorAll("pre.mermaid");
    if (!nodes.length) return;
    // Material's Mermaid integration initializes on DOMContentLoaded; we
    // piggy-back on the same window.mermaid instance.
    window.mermaid.initialize(currentPalette());
    nodes.forEach(function (el) {
      // Replace the source element so mermaid.render regenerates the SVG
      // with the new palette instead of caching the previous render.
      var src = el.textContent;
      var container = document.createElement("div");
      container.className = "mermaid";
      container.textContent = src;
      el.parentNode.replaceChild(container, el);
    });
    window.mermaid.run({ nodes: document.querySelectorAll(".mermaid") });
  }

  document.addEventListener("DOMContentLoaded", function () {
    rerender();
    // Material toggles `data-md-color-scheme` on <body> when the user
    // switches palette. Observe it and re-render so diagrams flip too.
    var body = document.body;
    var obs = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        if (mutations[i].attributeName === "data-md-color-scheme") {
          rerender();
          break;
        }
      }
    });
    obs.observe(body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  });
})();
