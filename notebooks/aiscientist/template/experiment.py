"""Baseline experiment: a small MLP classifier on two built-in scikit-learn datasets.

The AI Scientist's template contract (Sec. 3 of the paper, `templates/*/experiment.py` in the
repository): the script must accept ``--out_dir``, run a *cheap* baseline, and write
``final_info.json`` inside ``out_dir`` as ``{key: {"means": {...}}}`` plus any raw artefacts the
plotting script needs.  Everything here runs on CPU in a few seconds.
"""
import argparse
import json
import os
import os.path as osp
import pickle
import time
import warnings

import numpy as np
from sklearn.datasets import load_breast_cancer, load_digits
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=ConvergenceWarning)

DATASETS = ["digits", "breast_cancer"]
SEEDS = [0, 1, 2]


def get_dataset(name):
    if name == "digits":
        d = load_digits()
    elif name == "breast_cancer":
        d = load_breast_cancer()
    else:
        raise ValueError(f"unknown dataset {name}")
    return d.data.astype(np.float64), d.target


def train_and_eval(dataset_name, seed):
    """Train the baseline model on one dataset with one seed and return its metrics."""
    X, y = get_dataset(dataset_name)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y
    )

    scaler = StandardScaler().fit(X_train)
    X_train, X_test = scaler.transform(X_train), scaler.transform(X_test)

    model = MLPClassifier(
        hidden_layer_sizes=(64,),
        activation="relu",
        alpha=1e-4,
        learning_rate_init=1e-3,
        batch_size=64,
        max_iter=60,
        random_state=seed,
    )
    start_time = time.time()
    model.fit(X_train, y_train)
    training_time = time.time() - start_time

    proba = model.predict_proba(X_test)
    test_acc = accuracy_score(y_test, proba.argmax(axis=1))
    test_loss = log_loss(y_test, proba, labels=list(range(proba.shape[1])))
    train_acc = accuracy_score(y_train, model.predict(X_train))
    return {
        "metrics": {
            "test_accuracy": float(test_acc),
            "test_loss": float(test_loss),
            "train_accuracy": float(train_acc),
            "training_time": float(training_time),
        },
        "train_loss_curve": [float(v) for v in model.loss_curve_],
    }


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    final_infos, all_results = {}, {}
    for dataset_name in DATASETS:
        per_seed = [train_and_eval(dataset_name, seed) for seed in SEEDS]
        keys = per_seed[0]["metrics"].keys()
        means = {k: float(np.mean([r["metrics"][k] for r in per_seed])) for k in keys}
        stderrs = {
            k: float(np.std([r["metrics"][k] for r in per_seed]) / np.sqrt(len(SEEDS))) for k in keys
        }
        final_infos[dataset_name] = {"means": means, "stderrs": stderrs}
        all_results[dataset_name] = {
            "train_loss_curves": [r["train_loss_curve"] for r in per_seed],
            "seeds": SEEDS,
        }
        print(f"{dataset_name}: " + ", ".join(f"{k}={v:.4f}" for k, v in means.items()))

    with open(osp.join(out_dir, "final_info.json"), "w") as f:
        json.dump(final_infos, f, indent=2)
    with open(osp.join(out_dir, "all_results.pkl"), "wb") as f:
        pickle.dump(all_results, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=str, default="run_0")
    args = parser.parse_args()
    main(args.out_dir)
