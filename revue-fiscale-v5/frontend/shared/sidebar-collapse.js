/**
 * Collapse sidebar — partagé console (/console) et billing (/billing).
 * CSS : saas-ds.css (.app-frame.sidebar-collapsed).
 *
 * Usage :
 *   RfSidebarCollapse.init({ storageKey: "rf-sidebar-collapsed-console" });
 */
(function (global) {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function lire(storageKey) {
    try {
      return localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  }

  /**
   * @param {string} storageKey
   * @param {boolean} on
   * @param {{ frameId?: string, buttonId?: string }} [opts]
   */
  function appliquer(storageKey, on, opts) {
    const frameId = (opts && opts.frameId) || "vue-app";
    const buttonId = (opts && opts.buttonId) || "btn-sidebar-collapse";
    const frame = $(frameId);
    if (!frame) return;
    frame.classList.toggle("sidebar-collapsed", !!on);
    const btn = $(buttonId);
    if (btn) {
      btn.setAttribute("aria-expanded", on ? "false" : "true");
      btn.title = on ? "Étendre le menu" : "Réduire le menu";
      btn.setAttribute("aria-label", btn.title);
    }
    try {
      localStorage.setItem(storageKey, on ? "1" : "0");
    } catch {
      /* ignore quota / private mode */
    }
  }

  /**
   * Branche le bouton collapse et restaure l’état localStorage.
   * @param {{ storageKey: string, frameId?: string, buttonId?: string }} opts
   */
  function init(opts) {
    if (!opts || !opts.storageKey) {
      throw new Error("RfSidebarCollapse.init : storageKey requis");
    }
    const storageKey = opts.storageKey;
    const buttonId = opts.buttonId || "btn-sidebar-collapse";
    const btn = $(buttonId);
    if (btn) {
      btn.addEventListener("click", () => {
        appliquer(storageKey, !lire(storageKey), opts);
      });
    }
    appliquer(storageKey, lire(storageKey), opts);
  }

  global.RfSidebarCollapse = {
    lire: lire,
    appliquer: appliquer,
    init: init,
  };
})(typeof window !== "undefined" ? window : globalThis);
