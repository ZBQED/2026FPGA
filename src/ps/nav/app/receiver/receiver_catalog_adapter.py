"""Catalog validation helper for the teammate's EXISTING receiver.

Call only AFTER existing envelope, boot/sequence deduplication, TTL, and current
voice-turn checks. It does not replace those checks, issue ACKs or play videos.
"""
import json
import math
from pathlib import Path

CATALOG_VERSION="2026.10.31-seven-extension-v1"
REJECTION_CLASSES=frozenset((15,16,17))


def catalog_action(payload, catalog_path):
    if not isinstance(payload,dict):raise ValueError("payload must be an object")
    if payload.get("schema_version")!="b_speech_result_v0.1" or payload.get("event")!="speech_result":
        raise ValueError("unsupported speech result")
    if payload.get("status") in ("rejected","error"):
        return None
    if payload.get("status")!="candidate":raise ValueError("unknown result status")
    if payload.get("intent_table_version")!=CATALOG_VERSION:
        raise ValueError("intent catalog version mismatch")
    top=payload.get("top3")
    if not isinstance(top,list) or not top or not isinstance(top[0],dict):raise ValueError("missing top1")
    best=top[0]
    cls=best.get("model_class")
    if type(cls) is not int:raise ValueError("model_class must be an integer")
    if cls in REJECTION_CLASSES:return None
    catalog=json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    if catalog.get("version")!=CATALOG_VERSION:raise ValueError("local catalog version mismatch")
    label=next((r for r in catalog["intents"] if r["model_class"]==cls),None)
    if label is None:raise ValueError("unknown business model_class")
    if (type(best.get("intent_id")) is not int or best["intent_id"]!=label["intent_id"]
            or best.get("intent_id_hex")!=label["intent_id_hex"] or best.get("code")!=label["code"]):
        raise ValueError("intent id/class/code mismatch")
    score=best.get("score")
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
        raise ValueError("invalid model score")
    return dict(intent_id=label["intent_id"],intent_id_hex=label["intent_id_hex"],
                model_class=cls,code=label["code"],text=label.get("meaning",label.get("sign_text","")),
                score=score,legacy_showcase_button=label.get("legacy_showcase_button"))


def video_for_action(action, asset_map_path):
    """Use a separate receiver-owned JSON object, e.g. {"0x2101":"videos/card.mp4"}."""
    if action is None:return None
    assets=json.loads(Path(asset_map_path).read_text(encoding="utf-8"))
    video=assets.get(action["intent_id_hex"])
    if not isinstance(video,str) or not video.strip():
        raise ValueError("video mapping is missing for "+action["intent_id_hex"])
    return video
