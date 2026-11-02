"""Query the local Kaptia knowledge pack using simple lexical ranking."""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "knowledge" / "index.jsonl"
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+")


def tokens(text):
    # Chinese text is retained as runs; add overlapping bigrams to improve short-query matches.
    result = []
    for item in TOKEN_RE.findall(text.lower()):
        result.append(item)
        if len(item) > 2 and not re.fullmatch(r"[a-z0-9_]+", item):
            result.extend(item[i:i + 2] for i in range(len(item) - 1))
    return result


def load_index():
    if not INDEX.is_file():
        raise FileNotFoundError("找不到 knowledge/index.jsonl；先執行 python scripts/build_knowledge_index.py")
    rows = []
    for line_no, line in enumerate(INDEX.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not all(isinstance(row.get(k), str) and row[k] for k in ("id", "source", "text")):
            raise ValueError(f"索引第 {line_no} 行缺少必要欄位")
        rows.append(row)
    if not rows:
        raise ValueError("知識索引是空的")
    return rows


def search(query, limit=4):
    rows = load_index()
    query_terms = set(tokens(query))
    if not query_terms:
        return []
    doc_terms = [Counter(tokens(row["text"])) for row in rows]
    df = Counter(term for terms in doc_terms for term in terms.keys())
    n = len(rows)
    ranked = []
    for row, counts in zip(rows, doc_terms):
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf * 2.2) / (tf + 1.2)
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["source"], pair[1]["id"]))
    return [{"score": round(score, 4), **row} for score, row in ranked[:limit]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="要查詢的 Kaptia 專案問題")
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()
    if args.top_k < 1 or args.top_k > 20:
        parser.error("--top-k 必須介於 1 到 20")
    results = search(args.query, args.top_k)
    if not results:
        print("[NO_MATCH] 本機知識索引沒有找到足夠的詞彙匹配；不要把這當成已查證答案。")
        return 2
    for i, row in enumerate(results, 1):
        print(f"--- 結果 {i} | score={row['score']} | 來源：{row['source']} | 章節：{row.get('section', '未知')} ---")
        print(row["text"])
        print()
    print("[INFO] 分數只代表詞彙匹配程度，不是答案正確率。生成答案時應保留來源路徑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
