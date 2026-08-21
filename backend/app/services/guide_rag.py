"""攻略知识库 — 手写 BM25 轻量检索（无向量库依赖）

v3.1 新增（2026-08-21）: 给 day_agent 供给"怎么玩才值"的经验内容（小红书风示例攻略）。

设计决策:
- 数据: backend/app/data/guides.json（静态资产随代码入库，非运行时数据）
- 检索: 景点名候选匹配（name 包含/被包含 + tags 兜底）→ 段落级 BM25 评分 → top-k 截断
- **选型判断（面试点）**: query 是确定性实体（景点名），BM25 足够；50 篇规模与
  向量检索效果无差异而成本差一个数量级；query 语义化（用户自由描述需求）才值得
  上向量库——retrieve() 接口已抽象，可替换实现不动调用方
- 降级: 知识库缺失/未命中 → 空列表，不阻断规划（延续降级透明原则）
- 中文分词: bigram（2-gram）切分，纯 Python 无 jieba 依赖
"""
import json
import math
import os
import re
from collections import Counter

# backend/app/services/guide_rag.py → 上溯两级 = backend/app/ → app/data/guides.json
GUIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "data", "guides.json")

_BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """中文 bigram 分词 + 英文/数字原样（轻量，无 jieba）。"""
    tokens = []
    for seg in _BIGRAM_RE.findall(text.lower()):
        if len(seg) == 1:
            tokens.append(seg)
        elif re.fullmatch(r"[\u4e00-\u9fff]+", seg):
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
        else:
            tokens.append(seg)
    return tokens


def _bm25_score(query_tokens: list[str], doc_tokens: list[str],
                doc_tf: Counter, df: dict, N: int, avg_len: float,
                k1: float = 1.5, b: float = 0.75) -> float:
    """BM25 评分（手写：idf 基于全段落集合，预计算 df 避免重复分词）。"""
    score = 0.0
    doc_len = len(doc_tokens)
    for t in set(query_tokens):
        df_t = df.get(t, 0)
        if df_t == 0:
            continue
        idf = math.log(1 + (N - df_t + 0.5) / (df_t + 0.5))
        f = doc_tf.get(t, 0)
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * doc_len / avg_len))
    return score


class GuideRAG:
    """攻略知识库检索器（段落级 BM25，引用可溯源）。"""

    def __init__(self, path: str | None = None):
        self.path = path or GUIDES_PATH
        self.guides: list[dict] = []
        self.paras: list[tuple[int, int, str]] = []   # (guide_idx, para_idx, text)
        self._doc_tokens: list[list[str]] = []
        self._doc_tf: list[Counter] = []
        self._df: dict = {}
        self._avg_len = 0.0
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            self.guides = json.load(f)
        for gi, g in enumerate(self.guides):
            paras = [p.strip() for p in re.split(r"\n{2,}", g.get("content", ""))
                     if p.strip()]
            for pi, p in enumerate(paras):
                self.paras.append((gi, pi, p))
        # 预计算段落 token 统计（BM25 idf/avg_len 基准）
        for _, _, text in self.paras:
            toks = _tokenize(text)
            self._doc_tokens.append(toks)
            self._doc_tf.append(Counter(toks))
        self._df = Counter(t for toks in self._doc_tokens for t in set(toks))
        n = len(self._doc_tokens)
        self._avg_len = (sum(len(t) for t in self._doc_tokens) / n) if n else 0.0

    # ================================================================
    # 公共接口
    # ================================================================

    def retrieve(self, name: str, city: str | None = None,
                 top_k: int = 2, max_chars: int = 300) -> list[dict]:
        """按景点名检索攻略段落。

        返回 [{"guide": 攻略名, "city": 城市, "tag": 段标签, "text": 截断文本}, ...]
        未命中/知识库缺失 → []（降级透明）。
        """
        if not self.paras or not name:
            return []

        # ── 1. 候选攻略: name 匹配（包含/被包含），城市过滤 ──
        candidates = []
        for gi, g in enumerate(self.guides):
            gname = g.get("name", "")
            if name in gname or gname in name:
                if city and g.get("city") and g["city"] != city:
                    continue  # 严格城市过滤（攻略跨城市场景少，宁缺毋滥）
                candidates.append(gi)
        if not candidates:
            # ── 2. tags 兜底（攻略名不含景点名，但标签覆盖）──
            for gi, g in enumerate(self.guides):
                if city and g.get("city") and g["city"] != city:
                    continue
                if any(name in t or t in name for t in g.get("tags", [])):
                    candidates.append(gi)
        if not candidates:
            return []

        # ── 3. 候选段落 BM25 评分 ──
        # query 增强: 景点名 + 通用攻略意图词"玩法"——攻略段落通常不重复主题词
        #（如故宫玩法段不含"故宫"字样），纯主题词 query 会大面积零命中；意图词
        # 匹配段落标签前缀【玩法】,这是轻量 RAG 的经典补偿（可讲）。
        query_tokens = _tokenize(name) + _tokenize("玩法")
        scored = []
        for pi, (gi, _, text) in enumerate(self.paras):
            if gi not in candidates:
                continue
            score = _bm25_score(query_tokens, self._doc_tokens[pi],
                                self._doc_tf[pi], self._df,
                                len(self._doc_tokens), self._avg_len)
            scored.append((score, gi, text))
        scored.sort(key=lambda x: x[0], reverse=True)

        # ── 4. 截断输出（保留段标签前缀，引用可溯源）──
        out = []
        for score, gi, text in scored[:top_k]:
            g = self.guides[gi]
            out.append({
                "guide": g.get("name", ""),
                "city": g.get("city", ""),
                "tag": text.split("】", 1)[0].lstrip("【") if "】" in text else "",
                "text": text[:max_chars],
            })
        return out

    def coverage(self, names: list[str]) -> dict:
        """攻略覆盖率（RAG 效果评估的可落地指标）: 命中景点数 / 总数。"""
        hit = sum(1 for n in names if self.retrieve(n, top_k=1))
        return {"total": len(names), "hit": hit,
                "rate": round(hit / len(names), 2) if names else 0.0}


_rag: GuideRAG | None = None


def get_guide_rag() -> GuideRAG:
    """全局单例（懒加载，知识库缺失返回空检索器不抛错）。"""
    global _rag
    if _rag is None:
        _rag = GuideRAG()
    return _rag
