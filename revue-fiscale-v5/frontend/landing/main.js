(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!reduce && "IntersectionObserver" in window) {
    const revealEls = [...document.querySelectorAll(".reveal")];

    const markIn = (el) => {
      if (!el.classList.contains("is-in")) el.classList.add("is-in");
    };

    const revealIfVisible = () => {
      const vh = window.innerHeight || document.documentElement.clientHeight;
      for (const el of revealEls) {
        if (el.classList.contains("is-in")) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top < vh * 0.94 && rect.bottom > vh * 0.06) markIn(el);
      }
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            markIn(entry.target);
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -4% 0px", threshold: 0 }
    );

    revealEls.forEach((el) => observer.observe(el));
    revealIfVisible();
    window.addEventListener("scroll", revealIfVisible, { passive: true });
    window.addEventListener("load", revealIfVisible);
    window.addEventListener("hashchange", () => {
      window.requestAnimationFrame(revealIfVisible);
    });
  } else {
    document
      .querySelectorAll(".reveal")
      .forEach((el) => el.classList.add("is-in"));
  }

  const top = document.querySelector(".top");
  if (top) {
    const onScroll = () => {
      top.classList.toggle("top--scrolled", window.scrollY > 24);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  initBottomNav();
  initHeroSlider(reduce);
})();

function initBottomNav() {
  const nav = document.querySelector("[data-bottom-nav]");
  if (!nav) return;

  const sectionLinks = Array.from(nav.querySelectorAll("[data-nav-section]"));
  if (!sectionLinks.length) return;

  const sections = sectionLinks
    .map((link) => {
      const id = link.getAttribute("data-nav-section");
      const el = id ? document.getElementById(id) : null;
      return el ? { id, el, link } : null;
    })
    .filter(Boolean);

  const setActive = (id) => {
    for (const link of sectionLinks) {
      const match = link.getAttribute("data-nav-section") === id;
      link.classList.toggle("is-active", match);
      if (match) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  };

  const updateFromScroll = () => {
    const marker = window.innerHeight * 0.38;
    let current = sections[0]?.id || "contenu";

    for (const section of sections) {
      const top = section.el.getBoundingClientRect().top;
      if (top <= marker) current = section.id;
    }

    // Near top of page → Explorer
    if (window.scrollY < 80) current = "contenu";

    setActive(current);
  };

  sectionLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      const id = link.getAttribute("data-nav-section");
      if (!id) return;
      const target = document.getElementById(id);
      if (!target) return;

      e.preventDefault();
      setActive(id);
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      if (history.replaceState) {
        history.replaceState(null, "", id === "contenu" ? "#" : `#${id}`);
      }
    });
  });

  updateFromScroll();
  window.addEventListener("scroll", updateFromScroll, { passive: true });
  window.addEventListener("resize", updateFromScroll, { passive: true });
}

function initHeroSlider(reduceMotion) {
  const root = document.querySelector("[data-hero-slider]");
  if (!root) return;

  const slides = Array.from(root.querySelectorAll(".hero-slide"));
  const visuals = Array.from(document.querySelectorAll("[data-hero-visuals] [data-visual]"));
  const dots = Array.from(root.querySelectorAll("[data-hero-dot]"));
  const live = root.querySelector("[data-hero-live]");
  const btnPrev = root.querySelector("[data-hero-prev]");
  const btnNext = root.querySelector("[data-hero-next]");
  if (slides.length < 2) return;

  const INTERVAL_MS = 5500;
  let index = 0;
  let timer = null;
  let paused = false;

  function goTo(next, { announce = true } = {}) {
    const total = slides.length;
    index = ((next % total) + total) % total;

    slides.forEach((slide, i) => {
      const active = i === index;
      slide.classList.toggle("is-active", active);
      slide.setAttribute("aria-hidden", active ? "false" : "true");
    });

    visuals.forEach((viz) => {
      const i = Number(viz.getAttribute("data-visual"));
      viz.classList.toggle("is-active", i === index);
    });

    dots.forEach((dot, i) => {
      const active = i === index;
      dot.classList.toggle("is-active", active);
      dot.setAttribute("aria-selected", active ? "true" : "false");
      dot.tabIndex = active ? 0 : -1;
    });

    if (announce && live) {
      const title = slides[index].querySelector(".hero__title");
      live.textContent = title ? title.textContent.trim() : `Message ${index + 1}`;
    }
  }

  function stop() {
    if (timer != null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  function start() {
    if (reduceMotion || paused || document.hidden) return;
    stop();
    timer = window.setInterval(() => goTo(index + 1), INTERVAL_MS);
  }

  function pause() {
    paused = true;
    stop();
  }

  function resume() {
    paused = false;
    start();
  }

  btnPrev?.addEventListener("click", () => {
    goTo(index - 1);
    start();
  });

  btnNext?.addEventListener("click", () => {
    goTo(index + 1);
    start();
  });

  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      const i = Number(dot.getAttribute("data-hero-dot"));
      if (!Number.isNaN(i)) {
        goTo(i);
        start();
      }
    });
  });

  root.addEventListener("mouseenter", pause);
  root.addEventListener("mouseleave", resume);
  root.addEventListener("focusin", pause);
  root.addEventListener("focusout", (e) => {
    if (!root.contains(e.relatedTarget)) resume();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else if (!paused) start();
  });

  root.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      goTo(index - 1);
      start();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      goTo(index + 1);
      start();
    }
  });

  goTo(0, { announce: false });
  start();
}
