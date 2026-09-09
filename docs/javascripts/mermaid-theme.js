// Single mid-tone Mermaid palette that stays readable in both Material light
// and dark mode. Uses Mermaid's own themeVariables so the colors are baked
// into the generated SVG (CSS overrides lose to inline style="" attributes).
// The mid-tone greys + saturated accents chosen here have enough contrast on
// both white (#ffffff) and slate (#0f172a) backgrounds.

(function () {
  "use strict";

  var PALETTE = {
    theme: "base",
    themeVariables: {
      background: "#ffffff",
      primaryColor: "#cbd5e1",
      primaryBorderColor: "#334155",
      primaryTextColor: "#0f172a",
      secondaryColor: "#fde68a",
      secondaryBorderColor: "#92400e",
      secondaryTextColor: "#1a1a1a",
      tertiaryColor: "#bbf7d0",
      tertiaryBorderColor: "#166534",
      tertiaryTextColor: "#0f172a",
      lineColor: "#1e293b",
      textColor: "#0f172a",
      mainBkg: "#cbd5e1",
      nodeBorder: "#334155",
      clusterBkg: "#e2e8f0",
      clusterBorder: "#475569",
      actorBkg: "#cbd5e1",
      actorBorder: "#334155",
      actorTextColor: "#0f172a",
      actorLineColor: "#1e293b",
      signalColor: "#1e293b",
      signalTextColor: "#0f172a",
      labelBoxBkgColor: "#fde68a",
      labelBoxBorderColor: "#92400e",
      labelTextColor: "#1a1a1a",
      loopTextColor: "#1a1a1a",
      noteBkgColor: "#e2e8f0",
      noteBorderColor: "#475569",
      noteTextColor: "#0f172a",
      classText: "#0f172a",
      fillType0: "#cbd5e1",
      fillType1: "#fde68a",
      fillType2: "#bbf7d0",
      fillType3: "#fbcfe8",
      fillType4: "#a5f3fc",
      fillType5: "#fecaca",
      fillType6: "#ddd6fe",
      fillType7: "#fed7aa",
      git0: "#1e40af",
      git1: "#b45309",
      git2: "#15803d",
      git3: "#9d174d",
      git4: "#155e75",
      git5: "#991b1b",
      git6: "#6b21a8",
      git7: "#9a3412",
      commitLabelColor: "#ffffff",
      commitLabelBackground: "#334155",
      tagLabelColor: "#ffffff",
      tagLabelBackground: "#475569",
      tagLabelBorder: "#475569",
    },
    flowchart: { htmlLabels: true, curve: "basis" },
    sequence: { showSequenceNumbers: false },
    securityLevel: "loose",
  };

  function rerender() {
    if (typeof window.mermaid === "undefined") return;
    var nodes = document.querySelectorAll("pre.mermaid");
    if (!nodes.length) return;
    window.mermaid.initialize(PALETTE);
    nodes.forEach(function (el) {
      var src = el.textContent;
      var container = document.createElement("div");
      container.className = "mermaid";
      container.textContent = src;
      el.parentNode.replaceChild(container, el);
    });
    window.mermaid.run({ nodes: document.querySelectorAll(".mermaid") });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rerender);
  } else {
    rerender();
  }
})();
