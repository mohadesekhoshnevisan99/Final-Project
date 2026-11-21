# Google Cloud deployment and evaluation

The proposal uses an Ubuntu Compute Engine VM and a private Cloud Storage bucket. Docker Compose runs FastAPI, a dispatcher, RabbitMQ, workers, Redis, and PostgreSQL/pgvector on the VM. The API defaults to the VM's loopback address. Use an SSH port forward to demo it from a browser.

## 1. Provision the demo resources

Use Bash in [Cloud Shell](https://docs.cloud.google.com/shell/docs/using-cloud-shell) or a local terminal with the Google Cloud CLI. Use a project with billing or course credits enabled. Replace the project and bucket names before running the commands. Bucket names are globally unique. Review the [Compute Engine pricing page](https://cloud.google.com/compute/all-pricing) for your region and check remaining course credits before provisioning.

```bash
export PROJECT="YOUR_GCP_PROJECT"
export REGION="us-central1"
export ZONE="us-central1-a"
export BUCKET="YOUR_GLOBALLY_UNIQUE_PRIVATE_BUCKET"
export VM="paper-similarity"
export SERVICE_ACCOUNT="paper-similarity"
export SA_EMAIL="${SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT"
gcloud services enable compute.googleapis.com storage.googleapis.com
gcloud iam service-accounts create "$SERVICE_ACCOUNT" --display-name="Paper similarity VM"
gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectUser"

gcloud compute instances create "$VM" --zone="$ZONE" --machine-type=e2-standard-2 \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=40GB --service-account="$SA_EMAIL" --scopes=cloud-platform
```

Use the service account attached to the VM through Application Default Credentials. The `cloud-platform` scope allows API calls, while the bucket IAM binding grants access to that bucket's objects. Keep JSON service-account keys out of the VM, repo, video, and submission. Use your project's existing SSH configuration. In a project that requires Identity-Aware Proxy, follow the official SSH firewall and IAM steps and append `--tunnel-through-iap` to the SSH command. [Compute Engine service accounts](https://docs.cloud.google.com/compute/docs/access/service-accounts) · [Cloud Storage IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles) · [SSH through IAP](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)

## 2. Start the service and import the corpus

SSH into the VM using `gcloud compute ssh "$VM" --zone="$ZONE"`. On the VM, install Docker Engine and the Compose plugin using the [official Ubuntu apt instructions](https://docs.docker.com/engine/install/ubuntu/#install-using-the-apt-repository). Commands below assume the login user can access the Docker socket. If you use the Docker group, sign out and back in after adding the user. [Manage Docker as a non-root user](https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user)

Clone your team's repository into the VM using a GitHub credential scoped to read that repository. From the checkout, prepare `.env`.

```bash
cp .env.example .env
nano .env
```

Set these values in the file. Use the exact bucket name created above without the `gs://` prefix.

```dotenv
APP_STORAGE_BACKEND=gcs
APP_GCS_BUCKET=YOUR_GLOBALLY_UNIQUE_PRIVATE_BUCKET
APP_MODEL_MODE=minilm
APP_INSTALL_MODEL=true
APP_MODEL_THREADS=1
APP_CACHE_ENABLED=true
APP_HOST=127.0.0.1
APP_PORT=8000
```

```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
```

Download `arxiv-metadata-oai-snapshot.json` from the [arXiv dataset page](https://www.kaggle.com/datasets/Cornell-University/arxiv). Extract the JSON Lines file from the archive. Put the snapshot on a machine with enough free disk space. From the repo on that machine, generate a fixed input file. The `prepare` command is independent of the running services.

```bash
python3 -m research_similarity.corpus prepare /path/to/arxiv-metadata-oai-snapshot.json \
  --output data/corpus.jsonl --limit 25000
sha256sum data/corpus.jsonl
```

Save the downloaded snapshot's version or date and the SHA-256 of the filtered file with your results. Transfer the filtered `data/corpus.jsonl` to the same relative path in the VM checkout using `gcloud compute scp data/corpus.jsonl "$VM":~/YOUR_REPO/data/corpus.jsonl --zone="$ZONE"`. From the VM checkout, run the importer and smoke test.

```bash
docker compose run --rm tools python -m research_similarity.corpus index data/corpus.jsonl --timeout 3600
curl -fsS http://127.0.0.1:8000/healthz
mkdir -p evidence
python3 scripts/smoke.py > evidence/smoke.json
```

Expect `papers` to be 25,000 for the proposed full snapshot. If importing takes longer than one hour, check `docker compose logs --tail 100 worker dispatcher` and the corpus progress before rerunning the same file. Use the fixed input file for all worker configurations. On a separate demo project, `data/demo.jsonl` gives a quick alternative corpus for checking the deployment. Use the full snapshot when reporting the proposed workload. [arXiv bulk metadata access](https://info.arxiv.org/help/bulk_data.html)

## 3. Open the demo in your browser

Run this from a **local** terminal with Google Cloud CLI, keeping it open during the recording. Adjust the local port if it is in use.

```bash
gcloud compute ssh "$VM" --zone="$ZONE" -- -N -L 8000:127.0.0.1:8000
```

Open [http://localhost:8000](http://localhost:8000). Submit a paper abstract, show its ranked results, then repeat the same query to demonstrate a Redis hit. The tunnel keeps FastAPI reachable through SSH with the VM's data services on the Compose network. [Google Cloud CLI SSH command](https://docs.cloud.google.com/sdk/gcloud/reference/compute/ssh)

## 4. Gather test evidence

From the VM checkout, run the test profile against the Docker Compose environment. It includes a NumPy comparison against an exact pgvector query. The test container receives `APP_TEST_DATABASE_URL` through Compose.

```bash
docker compose build test
docker compose run --rm test
```

Run controlled failures only in a dedicated demo or test deployment with exactly one worker and no other users. Enable a 12-second pause immediately after a claim by setting `APP_WORKER_DELAY_SECONDS=12` in that deployment's `.env`. Save the evidence and reset the delay before any timing experiment.

```bash
docker compose up -d --wait --scale worker=1
python3 scripts/failure_test.py all > evidence/failure-tests.json
docker compose logs --no-color worker dispatcher rabbitmq > evidence/failure-logs.txt
# In .env set APP_WORKER_DELAY_SECONDS=0, then apply it:
docker compose up -d --wait --scale worker=1
```

The first scenario waits for a real job claim, kills the worker, restarts it and checks for a second attempt. The broker scenario verifies a ready message survives a RabbitMQ restart. The cache scenario stops Redis and checks that a fresh query completes. Each scenario verifies the number and order of results.

## 5. Measure throughput and caching

Use the same `e2-standard-8` VM type (8 vCPUs, 32 GB RAM) across the worker-count sweep. If changing the demo VM's size, stop it, change the machine type, then restart it. Reconnect over SSH and rerun `docker compose up -d --wait` if needed. The VM boot disk preserves the Compose data volumes. [Change a Compute Engine machine type](https://docs.cloud.google.com/compute/docs/instances/changing-machine-type-of-stopped-instance)

```bash
gcloud compute instances stop "$VM" --zone="$ZONE"
gcloud compute instances set-machine-type "$VM" --zone="$ZONE" --machine-type=e2-standard-8
gcloud compute instances start "$VM" --zone="$ZONE"
```

Install Locust in a Python virtual environment on the client. To keep the load generator off the measured VM, use your local machine and its SSH tunnel for all runs. Note that latency includes the tunnel and the 250 ms polling interval. Use identical user count, spawn rate, duration, dataset, model, and workload across the sweep. Wait for the models to warm and any jobs from earlier runs to drain before each measurement. The worker model should use one CPU thread per replica to reduce oversubscription. If needed, adjust the initial concurrency on a pilot run, then keep it fixed across the recorded runs.

```bash
python3 -m venv .bench-venv
. .bench-venv/bin/activate
python -m pip install -r requirements-dev.txt
mkdir -p evidence
```

Run each scale command on the VM in order. After each scale change, run a short warmup from the client, then run the measured command below on the client. Update the CSV filename to match the worker count. Capture `docker stats --no-stream` from the VM during each run.

```bash
docker compose up -d --wait --scale worker=1
docker compose up -d --wait --scale worker=2
docker compose up -d --wait --scale worker=4
docker compose up -d --wait --scale worker=8
```

```bash
BENCH_REPEAT=0 locust -f scripts/locustfile.py --host http://127.0.0.1:8000 \
  --headless -u 24 -r 4 -t 120s --stop-timeout 120 --csv evidence/unique-w1
```

For the cache comparison, keep four workers, repeat the same fixed query set and record two 120-second runs. Set `APP_CACHE_ENABLED=false` in the VM's `.env`, apply with `docker compose up -d --wait --scale worker=4 api worker`, and record `repeated-cache-off`. Switch the setting to `true`, reapply Compose, then run a brief repeated-query warmup before recording `repeated-cache-on`. The latter measures a warm cache. Use the same client and VM for both.

```bash
BENCH_REPEAT=1 locust -f scripts/locustfile.py --host http://127.0.0.1:8000 \
  --headless -u 24 -r 4 -t 120s --stop-timeout 120 --csv evidence/repeated-cache-off

# Change the VM setting and warm the cache before running this command.
BENCH_REPEAT=1 locust -f scripts/locustfile.py --host http://127.0.0.1:8000 \
  --headless -u 24 -r 4 -t 120s --stop-timeout 120 --csv evidence/repeated-cache-on
python scripts/compare_runs.py evidence/*_stats.csv > evidence/summary.csv
```

`JOB / end-to-end` is one observation per search and includes polling. `POST /jobs` and `GET /jobs/{id}` describe HTTP requests. Use the job rows for completed searches/sec and p50/p95 latency, and check failures before interpreting percentiles. The summary's cache hit percentage uses successful jobs as its denominator. Save the machine type, corpus checksum, model mode, worker count, test date, load settings, and client location with the measurements. [Locust quickstart](https://docs.locust.io/en/stable/quickstart.html)

## 6. Stop or remove the resources

Stop the VM after the demo if you still need to keep its volumes. Persistent disks and Cloud Storage can accrue charges while the VM is stopped. After saving evidence, use the Cloud Console to delete the class VM and its boot disk and, when the stored submissions and corpus are no longer needed, delete the private project bucket and service account. Keep the video accessible to the graders.
