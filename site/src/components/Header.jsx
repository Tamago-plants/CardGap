// スティッキーヘッダ: ロゴ / 横断検索 / 更新時刻(JST+相対) / USD/JPY / テーマ切替 / タブ。
import { useEffect, useMemo, useRef, useState } from "react";
import { fmtDateTimeJst, fmtRelative } from "../lib/format.js";
import { searchCards } from "../lib/data.js";

const TABS = [
  { path: "/dashboard", label: "ダッシュボード" },
  { path: "/rankings", label: "ランキング" },
  { path: "/market", label: "市場マップ" },
  { path: "/deals", label: "案件一覧" },
];

function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}
function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}
function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function SearchBox({ index, onOpenCard }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);

  const results = useMemo(() => searchCards(index, q), [index, q]);

  useEffect(() => {
    const onDoc = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDoc);
    return () => document.removeEventListener("pointerdown", onDoc);
  }, []);

  const pick = (card) => {
    setOpen(false);
    setQ("");
    onOpenCard(card.card_id);
  };

  const onKey = (e) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[active]) pick(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="searchbox" ref={boxRef}>
      <span className="search-icon">
        <SearchIcon />
      </span>
      <input
        className="search-input"
        type="search"
        role="combobox"
        aria-expanded={open && q.trim() !== ""}
        aria-label="カード横断検索"
        placeholder="カード名・型番・英名で検索"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {open && q.trim() !== "" && (
        <div className="search-pop" role="listbox">
          {results.length === 0 ? (
            <div className="search-empty">該当するカードがありません</div>
          ) : (
            results.map((c, i) => (
              <button
                key={c.card_id}
                type="button"
                role="option"
                aria-selected={i === active}
                className={`search-item${i === active ? " active" : ""}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(c)}
              >
                <span className="s-name">{c.display_name}</span>
                <span className="s-sub">
                  {c.dealCount > 0 ? `案件${c.dealCount}件` : "履歴のみ"}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function Header({ summary, searchIndex, path, onNavigate, theme, onToggleTheme, onOpenCard }) {
  const generatedAt = summary && summary.generated_at;
  const fx = summary && summary.fx_rate;
  return (
    <header className="app-header">
      <div className="hdr-inner">
        <div className="brand">
          <span className="brand-badge" aria-hidden="true">
            C
          </span>
          CardGap
        </div>
        <SearchBox index={searchIndex} onOpenCard={onOpenCard} />
        <div className="hdr-meta">
          <div className="meta-item">
            <span className="meta-label">最終更新</span>
            <span className="meta-value num">
              {generatedAt ? (
                <>
                  {fmtDateTimeJst(generatedAt)} <span className="rel">({fmtRelative(generatedAt)})</span>
                </>
              ) : (
                "—"
              )}
            </span>
          </div>
          <div className="meta-item meta-fx">
            <span className="meta-label">USD/JPY</span>
            <span className="meta-value num">{fx ? fx.toFixed(2) : "—"}</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "ライトテーマに切替" : "ダークテーマに切替"}
            title={theme === "dark" ? "ライトテーマに切替" : "ダークテーマに切替"}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </div>
      <nav className="tabs" aria-label="メインナビゲーション">
        {TABS.map((t) => (
          <button
            key={t.path}
            type="button"
            className={`tab${path === t.path ? " active" : ""}`}
            aria-current={path === t.path ? "page" : undefined}
            onClick={() => onNavigate(t.path)}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </header>
  );
}
