// squarified treemap の自前実装(Bruls et al. のアルゴリズム)。
// items: {value >= 0 を含む任意オブジェクト} の配列 → {x,y,w,h,item} の配列。
// 0件・value合計0でも空配列を返すだけで壊れない。

/** 行内の最悪アスペクト比(1に近いほど正方形) */
function worstRatio(row, side) {
  const sum = row.reduce((a, v) => a + v, 0);
  if (sum <= 0 || side <= 0) return Infinity;
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = sum * sum;
  const side2 = side * side;
  return Math.max((side2 * max) / s2, s2 / (side2 * min));
}

export function squarify(items, x0, y0, w0, h0) {
  const valid = items.filter((it) => (it.value || 0) > 0);
  if (valid.length === 0 || w0 <= 0 || h0 <= 0) return [];
  const total = valid.reduce((a, it) => a + it.value, 0);
  const scale = (w0 * h0) / total;
  // 面積(px^2)に正規化して降順に
  const nodes = valid
    .map((it) => ({ item: it, area: it.value * scale }))
    .sort((a, b) => b.area - a.area);

  const out = [];
  let x = x0,
    y = y0,
    w = w0,
    h = h0;
  let row = []; // 現在の行に積んだ面積

  const layoutRow = () => {
    const sum = row.reduce((a, n) => a + n.area, 0);
    const horizontal = w >= h; // 短辺に沿って並べる
    const side = horizontal ? h : w;
    const thickness = side > 0 ? sum / side : 0;
    let offset = 0;
    for (const n of row) {
      const len = thickness > 0 ? n.area / thickness : 0;
      if (horizontal) {
        out.push({ x, y: y + offset, w: thickness, h: len, item: n.item });
      } else {
        out.push({ x: x + offset, y, w: len, h: thickness, item: n.item });
      }
      offset += len;
    }
    if (horizontal) {
      x += thickness;
      w -= thickness;
    } else {
      y += thickness;
      h -= thickness;
    }
    row = [];
  };

  for (const n of nodes) {
    const side = Math.min(w, h);
    const areas = row.map((r) => r.area);
    if (row.length === 0 || worstRatio([...areas, n.area], side) <= worstRatio(areas, side)) {
      row.push(n); // 追加しても悪化しないなら同じ行へ
    } else {
      layoutRow();
      row.push(n);
    }
  }
  if (row.length > 0) layoutRow();
  return out;
}
