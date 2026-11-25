# Report source

The English report builds from `build_report.py` and `report-evidence.json`. The archived measurements and machine context are in `docs/evidence/`. A new experiment updates `report-evidence.json` with its deployment and workload, and the report is rebuilt from it.

From the repository root:

```sh
python -m pip install reportlab==4.4.9
python docs/report/build_report.py --output Research-Paper-Similarity-Report.pdf
```
