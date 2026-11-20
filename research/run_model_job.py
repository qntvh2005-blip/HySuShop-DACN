"""Run an explicit experiment without changing the website's active model."""

import argparse
from pathlib import Path

from research.data.dataset import ResearchDataset
from research.evaluation.experiment import run_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    reports = args.reports.resolve()
    artifacts = args.artifacts.resolve()
    paths = [dataset, reports, artifacts]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if first == second or first in second.parents or second in first.parents:
                parser.error("Dataset, report and artifact directories must be separate.")
    if reports.exists() or artifacts.exists():
        parser.error("Use new output directories to preserve existing experiments.")
    research = ResearchDataset(dataset)
    if research.manifest.get("source_kind") != "official_raw":
        parser.error("This launcher requires a validated official dataset.")
    result = run_experiment(dataset, reports, artifacts)
    print(f"Completed: {result['artifact_directory']}")
    print("The website's active model and catalog were not changed.")


if __name__ == "__main__":
    main()
