"""NumPy-only inference shared by the PC candidate and the offline board patch."""
import json
import time
from pathlib import Path
import numpy as np
import feature_contract as feature_lib

REJECTION_CLASSES = frozenset((15, 16, 17))


def temporal_summary(feature):
    feature = np.asarray(feature, dtype=np.float32)
    if feature.shape != (398, 40) or not np.isfinite(feature).all():
        raise ValueError("Expected finite (398, 40) Log-Mel.")
    energy = feature.mean(axis=1)
    active = feature[energy >= max(-18.0, float(energy.max()) - 6.0)]
    if len(active) < 4:
        active = feature
    pieces = [active.mean(axis=0), active.std(axis=0),
              np.percentile(active, 25, axis=0), np.percentile(active, 75, axis=0),
              np.mean(np.abs(np.diff(active, axis=0)), axis=0)]
    for block in np.array_split(active, 4, axis=0):
        pieces.extend([block.mean(axis=0), block.std(axis=0)])
    return np.concatenate(pieces).astype(np.float32)


def load_model(path):
    with np.load(path, allow_pickle=False) as z:
        model = {k: z[k].copy() for k in ("feature_mean", "feature_std", "weights", "bias", "class_order")}
    n = len(model["class_order"])
    if (model["weights"].shape != (n, 520) or model["bias"].shape != (n,)
            or model["feature_mean"].shape != (520,) or model["feature_std"].shape != (520,)):
        raise ValueError("Model array contract mismatch.")
    if len(set(map(int, model["class_order"]))) != n:
        raise ValueError("Duplicate model classes.")
    if not all(np.isfinite(a).all() for a in model.values()):
        raise ValueError("Nonfinite model.")
    model["feature_std"] = np.where(model["feature_std"] < 1e-6, 1., model["feature_std"])
    return model


def probabilities(summaries, model):
    x = np.atleast_2d(np.asarray(summaries, dtype=np.float32))
    logits = ((x - model["feature_mean"]) / model["feature_std"]) @ model["weights"].T + model["bias"]
    values = np.exp(logits - logits.max(axis=1, keepdims=True))
    return values / values.sum(axis=1, keepdims=True)


def infer_feature(feature, model_path, catalog_path, utterance_id=0,
                  noise_rms=0., signal_rms=0.):
    started = time.perf_counter()
    model = load_model(model_path)
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    labels = {int(r["model_class"]): r for r in catalog["intents"] + catalog["rejection_classes"]}
    p = probabilities(temporal_summary(feature), model)[0]
    top = []
    for row in np.argsort(p)[::-1][:3]:
        c = int(model["class_order"][row])
        label = labels[c]
        top.append(dict(model_class=c, intent_id=int(label["intent_id"]),
                        intent_id_hex=label["intent_id_hex"], code=label["code"], score=float(p[row])))
    snr = None
    if signal_rms > 0 and noise_rms > 0:
        snr = int(np.clip(np.rint(20 * np.log10(signal_rms / noise_rms) * 256), 0, 65535))
    metadata_path = Path(model_path).with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    return dict(schema_version="b_speech_result_v0.1", event="speech_result",
                status="rejected" if top[0]["model_class"] in REJECTION_CLASSES else "candidate",
                model_version=metadata.get("model_version", Path(model_path).stem),
                intent_table_version=catalog["version"], utterance_id=int(utterance_id), top3=top,
                vad_state="speech", snr_q8=snr, timestamp_us=time.time_ns() // 1000, error_code=0,
                feature_shape=[398, 40], summary_feature_count=520,
                elapsed_ms=(time.perf_counter() - started) * 1000.)


def wrap_message(result, sequence):
    return dict(protocol_version="integration_network_v0.1", source="B",
                message_type="speech_result", sequence=int(sequence),
                timestamp_ms=time.time_ns() // 1000000, payload=result)
