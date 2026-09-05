"""Toy "champion" training script p* for the AutoScientists notebook.

Mirrors the shape of the paper's programs: a training script with top-level numeric
hyperparameters that agents edit one at a time, and a stochastic evaluation metric
(validation accuracy of an sklearn MLP on the digits dataset) that depends on --seed.
Higher is better. Runs in a few seconds on CPU.

Usage: python train.py --seed 0   -> prints a single JSON line {"metric": ..., "seed": ...}
"""
import argparse
import json
import time
import warnings

import numpy as np
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

# ---- hyperparameters (the "numeric parameters" an analyst audits, App. A.7) ----
HIDDEN = 32          # hidden units in the single hidden layer
LR = 0.001           # initial learning rate (adam)
ALPHA = 0.0001       # L2 penalty
MAX_ITER = 30        # training epochs
BATCH = 64           # minibatch size
BETA_1 = 0.9         # adam beta_1
VAL_FRACTION = 0.25  # held-out fraction (fixed split, seed-independent)
SCALE = 1            # 1 = standardise features, 0 = raw pixels


def run(seed: int) -> float:
    X, y = load_digits(return_X_y=True)
    X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=VAL_FRACTION, random_state=1234, stratify=y)
    if SCALE:
        sc = StandardScaler().fit(X_tr)
        X_tr, X_va = sc.transform(X_tr), sc.transform(X_va)
    clf = MLPClassifier(
        hidden_layer_sizes=(HIDDEN,),
        learning_rate_init=LR,
        alpha=ALPHA,
        max_iter=MAX_ITER,
        batch_size=BATCH,
        beta_1=BETA_1,
        random_state=seed,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clf.fit(X_tr, y_tr)
    return float(clf.score(X_va, y_va))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    t0 = time.time()
    metric = run(args.seed)
    print(json.dumps({"metric": metric, "seed": args.seed, "seconds": round(time.time() - t0, 2)}))
