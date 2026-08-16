// クリップされないホバーツールチップ。
// overflow コンテナ(テーブル・ドロワー)内でも切れないよう、
// createPortal + position:fixed で body 直下に描画する。ホバーとフォーカスの両対応。
import { useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function HoverTip({ tip, children, className = "", style, ariaLabel, width = 230 }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);

  const show = () => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const x = Math.min(Math.max(8, r.left + r.width / 2 - width / 2), window.innerWidth - width - 8);
    setPos({ x, top: r.top, bottom: r.bottom });
  };
  const hide = () => setPos(null);

  // 上に十分な余白があれば上、なければ下に出す
  const placement =
    pos && pos.top > 200
      ? { left: pos.x, bottom: window.innerHeight - pos.top + 8, width }
      : pos
        ? { left: pos.x, top: pos.bottom + 8, width }
        : null;

  return (
    <span
      ref={ref}
      className={className}
      style={style}
      tabIndex={0}
      aria-label={ariaLabel}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {pos &&
        createPortal(
          <span className="tipfix" role="tooltip" style={placement}>
            {tip}
          </span>,
          document.body
        )}
    </span>
  );
}
