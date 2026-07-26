import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";

type Side = "top" | "bottom";
type Align = "center" | "left" | "right";

type TooltipProps = {
  /** Texte process / aide — court (≤ 2 lignes à l’écran). */
  label: string;
  children: ReactNode;
  side?: Side;
  className?: string;
};

type InfoTipProps = {
  label: string;
  side?: Side;
  /** Libellé accessible du bouton pastille. */
  ariaLabel?: string;
  className?: string;
};

function useTipDismiss(
  open: boolean,
  setOpen: (v: boolean) => void,
  rootRef: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key !== "Escape") return;
      setOpen(false);
      const focusable = rootRef.current?.querySelector<HTMLElement>(
        "button.tip-pastille, button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      focusable?.focus();
    }
    function onPointer(e: PointerEvent) {
      const el = rootRef.current;
      if (el && !el.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, setOpen, rootRef]);
}

function useSmartPlacement(
  open: boolean,
  rootRef: RefObject<HTMLElement | null>,
  bubbleRef: RefObject<HTMLElement | null>,
  preferred: Side,
) {
  const [side, setSide] = useState<Side>(preferred);
  const [align, setAlign] = useState<Align>("center");

  useLayoutEffect(() => {
    if (!open) {
      setSide(preferred);
      setAlign("center");
      return;
    }
    const root = rootRef.current;
    const bubble = bubbleRef.current;
    if (!root || !bubble) return;

    const r = root.getBoundingClientRect();
    const b = bubble.getBoundingClientRect();
    const pad = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let nextSide: Side = preferred;
    if (preferred === "top" && r.top < b.height + pad + 4) nextSide = "bottom";
    if (preferred === "bottom" && vh - r.bottom < b.height + pad + 4)
      nextSide = "top";
    if (nextSide === "top" && r.top < b.height + pad) nextSide = "bottom";
    if (nextSide === "bottom" && vh - r.bottom < b.height + pad) nextSide = "top";

    let nextAlign: Align = "center";
    const centerX = r.left + r.width / 2;
    const half = b.width / 2;
    if (centerX - half < pad) nextAlign = "left";
    else if (centerX + half > vw - pad) nextAlign = "right";

    setSide(nextSide);
    setAlign(nextAlign);
  }, [open, preferred, rootRef, bubbleRef]);

  return { side, align };
}

function tipClass(open: boolean, className: string): string {
  return ["tip", open ? "is-open" : "", className].filter(Boolean).join(" ");
}

/**
 * Infobulle accessible — survol + focus clavier.
 * Placement intelligent (flip + clamp) ; `title` en repli mobile.
 */
export function Tooltip({
  label,
  children,
  side = "top",
  className = "",
}: TooltipProps) {
  const tipId = useId();
  const rootRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const place = useSmartPlacement(open, rootRef, bubbleRef, side);

  const child = Children.only(children);
  const described = isValidElement(child)
    ? cloneElement(child as ReactElement<Record<string, unknown>>, {
        "aria-describedby": tipId,
        title:
          typeof (child.props as { title?: string }).title === "string"
            ? (child.props as { title?: string }).title
            : label,
        onFocus: (e: FocusEvent) => {
          setOpen(true);
          const prev = (child.props as { onFocus?: (ev: FocusEvent) => void })
            .onFocus;
          prev?.(e);
        },
        onBlur: (e: FocusEvent) => {
          const next = e.relatedTarget as Node | null;
          if (!rootRef.current?.contains(next)) setOpen(false);
          const prev = (child.props as { onBlur?: (ev: FocusEvent) => void })
            .onBlur;
          prev?.(e);
        },
      })
    : children;

  return (
    <span
      ref={rootRef}
      className={tipClass(open, className)}
      data-side={place.side}
      data-align={place.align}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {described}
      <span
        ref={bubbleRef}
        id={tipId}
        className="tip-bubble"
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}

/**
 * Pastille ⓘ — libellés, bandeaux, KPI.
 * Survol / focus / appui (tactile) ; Échap ferme et rend le focus.
 */
export function InfoTip({
  label,
  side = "top",
  ariaLabel = "Aide",
  className = "",
}: InfoTipProps) {
  const tipId = useId();
  const rootRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const place = useSmartPlacement(open, rootRef, bubbleRef, side);

  useTipDismiss(open, setOpen, rootRef);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      e.currentTarget.focus();
    }
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen((v) => !v);
    }
  }

  return (
    <span
      ref={rootRef}
      className={tipClass(open, `tip-info ${className}`.trim())}
      data-side={place.side}
      data-align={place.align}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="tip-pastille"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-describedby={tipId}
        title={label}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={onKeyDown}
        onBlur={(e) => {
          const next = e.relatedTarget as Node | null;
          if (!rootRef.current?.contains(next)) setOpen(false);
        }}
      >
        <span className="tip-pastille-glyph" aria-hidden="true">
          i
        </span>
      </button>
      <span
        ref={bubbleRef}
        id={tipId}
        className="tip-bubble tip-bubble-info"
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
