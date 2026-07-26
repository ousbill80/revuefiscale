/**
 * InfoTip / Tooltip vanilla — port process de frontend/mission Tooltip.tsx
 * Tips process uniquement (pas de pédagogie fiscale inventée).
 */
(function (global) {
  "use strict";

  let uid = 0;
  function nextId() {
    uid += 1;
    return "rf-tip-" + uid;
  }

  function placeSmart(root, bubble, preferred) {
    const r = root.getBoundingClientRect();
    const b = bubble.getBoundingClientRect();
    const pad = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let side = preferred || "top";
    if (side === "top" && r.top < b.height + pad + 4) side = "bottom";
    if (side === "bottom" && vh - r.bottom < b.height + pad + 4) side = "top";
    if (side === "top" && r.top < b.height + pad) side = "bottom";
    if (side === "bottom" && vh - r.bottom < b.height + pad) side = "top";

    let align = "center";
    const centerX = r.left + r.width / 2;
    const half = b.width / 2;
    if (centerX - half < pad) align = "left";
    else if (centerX + half > vw - pad) align = "right";

    root.dataset.side = side;
    root.dataset.align = align;
  }

  function bindDismiss(root, setOpen) {
    function onKey(e) {
      if (e.key !== "Escape") return;
      setOpen(false);
      const focusable = root.querySelector(
        "button.tip-pastille, button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
      );
      if (focusable) focusable.focus();
    }
    function onPointer(e) {
      if (!root.contains(e.target)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return function unbind() {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }

  /**
   * Crée une pastille ⓘ dans `parent` (ou remplace un nœud placeholder).
   * @returns {HTMLElement} racine .tip
   */
  function mountInfoTip(parent, options) {
    const opts = options || {};
    const label = String(opts.label || "");
    const side = opts.side || "top";
    const ariaLabel = opts.ariaLabel || "Aide";
    const className = opts.className || "";

    const tipId = nextId();
    const root = document.createElement("span");
    root.className = ["tip", "tip-info", className].filter(Boolean).join(" ");
    root.dataset.side = side;
    root.dataset.align = "center";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tip-pastille";
    btn.setAttribute("aria-label", ariaLabel);
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-describedby", tipId);
    btn.title = label;
    btn.innerHTML = '<span class="tip-pastille-glyph" aria-hidden="true">i</span>';

    const bubble = document.createElement("span");
    bubble.id = tipId;
    bubble.className = "tip-bubble tip-bubble-info";
    bubble.setAttribute("role", "tooltip");
    bubble.textContent = label;

    root.appendChild(btn);
    root.appendChild(bubble);

    let open = false;
    let unbind = null;

    function setOpen(v) {
      open = !!v;
      root.classList.toggle("is-open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      bubble.setAttribute("aria-hidden", open ? "false" : "true");
      if (open) {
        placeSmart(root, bubble, side);
        if (!unbind) unbind = bindDismiss(root, setOpen);
      } else if (unbind) {
        unbind();
        unbind = null;
      }
    }

    bubble.setAttribute("aria-hidden", "true");

    root.addEventListener("mouseenter", function () {
      setOpen(true);
    });
    root.addEventListener("mouseleave", function () {
      setOpen(false);
    });
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(!open);
    });
    btn.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        btn.focus();
      }
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setOpen(!open);
      }
    });
    btn.addEventListener("blur", function (e) {
      const next = e.relatedTarget;
      if (!root.contains(next)) setOpen(false);
    });

    if (parent) parent.appendChild(root);
    return root;
  }

  /**
   * Monte toutes les pastilles déclaratives :
   * <span data-infotip="Texte process" data-infotip-side="top"></span>
   */
  function hydrate(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-infotip]").forEach(function (el) {
      if (el.dataset.infotipMounted === "1") return;
      const label = el.getAttribute("data-infotip") || "";
      if (!label) return;
      el.dataset.infotipMounted = "1";
      el.textContent = "";
      mountInfoTip(el, {
        label: label,
        side: el.getAttribute("data-infotip-side") || "top",
        ariaLabel: el.getAttribute("data-infotip-aria") || "Aide",
        className: el.getAttribute("data-infotip-class") || "",
      });
    });
  }

  global.RfInfoTip = {
    mount: mountInfoTip,
    hydrate: hydrate,
  };
})(typeof window !== "undefined" ? window : globalThis);
