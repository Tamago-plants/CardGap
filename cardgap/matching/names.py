"""カード名の日英対訳辞書。data/{pokemon,naruto}_names.csv を読む。

CSV形式: ヘッダ行 `name_ja,name_en`。以降1行1キャラ。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import normalize


@dataclass
class NameDict:
    ja_to_en: dict[str, str] = field(default_factory=dict)  # 正規化済み ja → en(原文)
    en_to_ja: dict[str, str] = field(default_factory=dict)

    def title_contains_name(self, title: str, name_ja: str, name_en: str) -> bool:
        """タイトルに日本語名または英語名(またはその対訳)が含まれるか。

        名前が複数語(空白区切り)の場合は「全語がタイトルに含まれる」判定
        (語順不問)。未開封ボックス等のキーワード監視
        (例: 'ナルト カードダス BOX 未開封')は語順どおりに出品されないため。
        単語1つの名前は従来どおり部分文字列一致。
        """
        t = normalize(title)
        candidates = {normalize(name_ja), normalize(name_en)}
        # 辞書に登録があれば対訳側も候補に加える(watchlist の表記ゆれ対策)
        en = self.ja_to_en.get(normalize(name_ja))
        if en:
            candidates.add(normalize(en))
        ja = self.en_to_ja.get(normalize(name_en))
        if ja:
            candidates.add(normalize(ja))
        for c in candidates:
            if not c:
                continue
            tokens = c.split(" ")
            if len(tokens) == 1:
                if c in t:
                    return True
            elif all(tok in t for tok in tokens):
                return True
        return False


def load_name_dict(csv_path: str | Path) -> NameDict:
    d = NameDict()
    path = Path(csv_path)
    if not path.exists():
        return d
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ja = (row.get("name_ja") or "").strip()
            en = (row.get("name_en") or "").strip()
            if not ja or not en:
                continue
            d.ja_to_en[normalize(ja)] = en
            d.en_to_ja[normalize(en)] = ja
    return d
