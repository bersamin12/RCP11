"""Plotting script for the template (The AI Scientist runs `python plot.py` after the experiments).

It reads every `run_*/final_info.json` + `run_*/all_results.pkl` in this directory and writes
`train_loss.png` and `test_accuracy.png`.  Only the runs listed in `labels` are plotted.
"""
import json
import os
import os.path as osp
import pickle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# LOAD FINAL RESULTS:
datasets = ["digits", "breast_cancer"]
folders = os.listdir("./")
final_results = {}
train_info = {}

for folder in sorted(folders):
    if folder.startswith("run") and osp.isdir(folder):
        with open(osp.join(folder, "final_info.json"), "r") as f:
            final_results[folder] = json.load(f)
        with open(osp.join(folder, "all_results.pkl"), "rb") as f:
            train_info[folder] = pickle.load(f)

# CREATE LEGEND -- PLEASE FILL IN YOUR RUN NAMES HERE
# Keep the names short, as these will be in the legend.
labels = {
    "run_0": "Baseline",
}

# Use the run key as the default label if not specified
runs = list(final_results.keys())
for run in runs:
    if run not in labels:
        labels[run] = run

colors = plt.get_cmap("tab10")(np.linspace(0, 1, max(len(runs), 2)))

# Plot 1: mean training-loss curve per dataset, one line per run
fig, axs = plt.subplots(1, len(datasets), figsize=(6 * len(datasets), 4), squeeze=False)
for j, dataset in enumerate(datasets):
    ax = axs[0][j]
    for i, run in enumerate(runs):
        curves = train_info[run][dataset]["train_loss_curves"]
        n = min(len(c) for c in curves)
        mean_curve = np.mean([c[:n] for c in curves], axis=0)
        ax.plot(mean_curve, label=labels[run], color=colors[i])
    ax.set_title(dataset)
    ax.set_xlabel("epoch")
    ax.set_ylabel("training loss")
    ax.legend()
plt.tight_layout()
plt.savefig("train_loss.png", dpi=110)
plt.close()

# Plot 2: test accuracy per dataset, one bar per run (error bars = standard error over seeds)
fig, ax = plt.subplots(figsize=(1.6 * len(runs) * len(datasets) + 3, 4))
width = 0.8 / max(len(runs), 1)
x = np.arange(len(datasets))
for i, run in enumerate(runs):
    means = [final_results[run][d]["means"]["test_accuracy"] for d in datasets]
    errs = [final_results[run][d].get("stderrs", {}).get("test_accuracy", 0.0) for d in datasets]
    ax.bar(x + i * width, means, width, yerr=errs, label=labels[run], color=colors[i])
ax.set_xticks(x + width * (len(runs) - 1) / 2)
ax.set_xticklabels(datasets)
ax.set_ylabel("test accuracy")
ax.set_ylim(0.9, 1.0)
ax.legend()
plt.tight_layout()
plt.savefig("test_accuracy.png", dpi=110)
plt.close()
print("wrote train_loss.png and test_accuracy.png for runs:", runs)
