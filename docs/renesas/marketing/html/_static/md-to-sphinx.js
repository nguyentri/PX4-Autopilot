/* Click or press Enter on a pre-rendered diagram to view it at natural size. */
(() => {
  const open = (img) => {
    const overlay = document.createElement("div");
    overlay.className = "md2s-lightbox";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", img.alt || "Diagram");
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    const large = document.createElement("img");
    large.src = img.currentSrc || img.src;
    large.alt = img.alt;
    overlay.append(close, large);
    const dismiss = () => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      img.focus();
    };
    const onKey = (event) => { if (event.key === "Escape") dismiss(); };
    overlay.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    close.focus();
  };

  const enhance = () => {
    document.querySelectorAll("figure.md2s-diagram img").forEach((img) => {
      img.tabIndex = 0;
      img.setAttribute("role", "button");
      img.title = "Enlarge diagram";
      img.addEventListener("click", () => open(img));
      img.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open(img);
        }
      });
    });
  };

  // Client-side Mermaid (sphinxcontrib-mermaid) forces every SVG to the full
  // column width, which blows small diagrams up. Cap each one at its natural
  // viewBox width; an inline !important declaration outranks the stylesheet.
  const fitClientSvg = (svg) => {
    if (svg.dataset.md2sFitted) return;
    const box = svg.viewBox && svg.viewBox.baseVal;
    if (!box || !box.width) return;
    svg.style.setProperty("max-width", `min(100%, ${box.width}px)`, "important");
    svg.style.setProperty("height", "auto", "important");
    svg.style.setProperty("margin", "0 auto", "important");
    svg.style.setProperty("display", "block", "important");
    svg.dataset.md2sFitted = "true";
  };
  const watchClientDiagrams = () => {
    const blocks = document.querySelectorAll("pre.mermaid, div.mermaid");
    if (!blocks.length) return;
    const scan = () => document.querySelectorAll("pre.mermaid svg, div.mermaid svg").forEach(fitClientSvg);
    scan();
    const observer = new MutationObserver(scan);
    blocks.forEach((block) => observer.observe(block, { childList: true, subtree: true }));
  };

  const start = () => {
    enhance();
    watchClientDiagrams();
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
