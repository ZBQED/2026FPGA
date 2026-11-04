"""Compose completed gesture words using the frozen catalog's exact order.

Pure Python 3.7; no model, device, network or UI dependencies. The caller owns
event deduplication, recognition thresholds and the turn/confirmation state.
"""
import json
import math
from pathlib import Path


DEFAULT_CATALOG = (Path(__file__).resolve().parents[1] / "phase1_udp" /
                   "config" / "sign_intents_v1.json")

# Only these five exact naming alignments are supported. The latest source
# vocabulary uses 好 while two source expressions retain OK; A uses 好 (idx11).
# The other aliases follow A's `name` and `intents` fields, not general synonyms.
# Keep the source catalog expressions and output_text unchanged.
TOKEN_ALIASES = {
    "OK": "好",           # idx 11: source expressions OK+我+挂号 / OK+我+缴费
    "感谢": "谢谢",       # idx 4: THANKS 谢谢
    "马桶": "卫生间",     # idx 2: TOILET_LOCATION 卫生间
    "化验": "检验科",     # idx 19: LAB_LOCATION 检验科
    "钱(现金)": "现金",   # idx 16: 现金支付 / 钱/现金
}


def normalize_token(token):
    """Align explicitly documented names; preserve all other words exactly."""
    if not isinstance(token, str) or not token or token.isspace():
        raise ValueError("手语词必须是非空文本")
    return TOKEN_ALIASES.get(token, token)


class OrderedIntentComposer:
    def __init__(self, catalog_path=None):
        path = DEFAULT_CATALOG if catalog_path is None else Path(catalog_path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = data.get("intents") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError("手语意图库缺少 intents 列表")
        counts = data.get("counts", {})
        if (not isinstance(counts, dict) or
                counts.get("intent_entries") != len(entries)):
            raise ValueError("手语意图库的意图数量与目录不一致")
        self._entries = []
        self._exact = {}
        source_orders = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("手语意图条目必须是对象")
            tokens = entry.get("tokens")
            text = entry.get("output_text")
            expression = entry.get("gesture_expression")
            order = entry.get("source_order")
            if (not isinstance(tokens, list) or not tokens or
                    any(not isinstance(token, str) or not token or token.isspace()
                        for token in tokens) or
                    not isinstance(text, str) or not text.strip() or
                    type(order) is not int or order <= 0 or
                    expression != "+".join(tokens)):
                raise ValueError("手语意图条目的词序、表达、正文或来源编号无效")
            sequence = tuple(normalize_token(token) for token in tokens)
            if sequence in self._exact or order in source_orders:
                raise ValueError("手语意图库包含重复词序或来源编号")
            saved = {"tokens": sequence, "text": text, "expression": expression,
                     "source_intent_order": order}
            self._entries.append(saved)
            self._exact[sequence] = saved
            source_orders.add(order)
        self.reset()

    def reset(self):
        """Start a fresh expression; only the caller may decide when to reset."""
        self._tokens = []
        self._confidences = []
        return self._recompute()

    def _recompute(self):
        """Match the complete current sequence after an append or explicit undo."""
        self._confidence = min(self._confidences) if self._confidences else -1.0
        self._status = "empty"
        self._text = ""
        self._source_order = None
        self._hint = "请按顺序完成本次手语表达。"
        if not self._tokens:
            return self.snapshot()
        sequence = tuple(self._tokens)
        matched = self._exact.get(sequence)
        if matched is not None:
            self._status = "matched"
            self._text = matched["text"]
            self._source_order = matched["source_intent_order"]
            self._hint = "组合已完整，请确认后发送；继续做动作会追加词语。"
            return self.snapshot()
        candidates = [entry for entry in self._entries
                      if entry["tokens"][:len(sequence)] == sequence]
        if not candidates:
            self._status = "unmatched"
            self._hint = "当前完整词序未匹配意图库，可撤回上一词或重新识别。"
        else:
            self._status = "prefix"
            if len(candidates) == 1:
                remaining = candidates[0]["tokens"][len(sequence):]
                self._hint = "请继续做：" + " → ".join(remaining) + "。"
            else:
                next_words = []
                for entry in candidates:
                    word = entry["tokens"][len(sequence)]
                    if word not in next_words:
                        next_words.append(word)
                self._hint = "请继续做下一个词：" + "、".join(next_words) + "。"
        return self.snapshot()

    def append(self, token, confidence):
        """Append one final word, preserving repetitions and the complete order.

        Invalid inputs raise ValueError without changing state. Every accepted
        action remains visible, including words after a match or a mismatch.
        Confidence is the minimum of accepted words, not sentence probability.
        """
        token = normalize_token(token)
        if (isinstance(confidence, bool) or
                not isinstance(confidence, (int, float)) or
                not 0 <= confidence <= 1 or not math.isfinite(confidence)):
            raise ValueError("手语词置信度必须是 0 到 1 之间的有限数值")
        self._tokens.append(token)
        self._confidences.append(float(confidence))
        return self._recompute()

    def undo(self):
        """Remove exactly the latest word; retain order and original confidence."""
        if self._tokens:
            self._tokens.pop()
            self._confidences.pop()
        return self._recompute()

    def snapshot(self):
        """Return a detached state dictionary suitable for the UI snapshot."""
        return {"tokens": list(self._tokens), "status": self._status,
                "text": self._text, "expression": "+".join(self._tokens),
                "confidence": self._confidence, "hint": self._hint,
                "source_intent_order": self._source_order}
