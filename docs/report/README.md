# Report source

The English report builds from `build_report.py` and `report-evidence.json`. The archived measurements and machine context are in `docs/evidence/`. If you run a new experiment, update the results with its deployment and workload before rebuilding. Inspect the rendered PDF before submitting it.

From the repository root:

```sh
python -m pip install reportlab==4.4.9
python docs/report/build_report.py --output Research-Paper-Similarity-Report.pdf
```
