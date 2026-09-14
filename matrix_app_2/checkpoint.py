import json
import os

import config


def _path(name):
    os.makedirs(config.CHECKPOINT_DIR, exist_ok=True)
    return os.path.join(config.CHECKPOINT_DIR, f"{name}.json")


def load(name):
    path = _path(name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f).get("last_id", 0)
    return 0


def save(name, last_id):
    with open(_path(name), "w") as f:
        json.dump({"last_id": last_id}, f)
