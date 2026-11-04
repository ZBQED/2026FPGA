"""Label loading and numerical helpers used by the speech service."""
import argparse
import json
from pathlib import Path
import numpy as np
from model_runtime import infer_feature, temporal_summary


def softmax(logits):
    values=np.exp(logits-np.max(logits))
    return values/values.sum()


def load_labels(path):
    c=json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(r["model_class"]):r for r in c["intents"]+c["rejection_classes"]}


