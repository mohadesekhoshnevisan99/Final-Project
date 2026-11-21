import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

parser = argparse.ArgumentParser(description='Build the five-page project report.')
parser.add_argument('--evidence', type=Path, default=Path(__file__).with_name('report-evidence.json'))
parser.add_argument('--output', type=Path, default=Path('Research-Paper-Similarity-Report.pdf'))
args = parser.parse_args()
OUT = args.output
E = json.loads(args.evidence.read_text(encoding='utf-8'))
W, H = 612, 792
L, R = 58, 554
INK = '#172B28'
GREEN = '#16654D'
MUTED = '#49615A'
RULE = '#CFDED5'
PALE = '#F0F6F1'
PAPER = '#FAFBF7'

c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
c.setTitle('Research-Paper Similarity Service')
c.setAuthor('Mohadeseh Khoshnevisan and Sepehr Rezaei')
c.setSubject('Datacenter term project report')


def para(value, x, y, w=R-L, size=11.0, leading=16.5, font='Helvetica', color=INK):
    style = ParagraphStyle('report', fontName=font, fontSize=size, leading=leading,
                           textColor=colors.HexColor(color), alignment=TA_LEFT)
    p = Paragraph(value, style)
    _, height = p.wrap(w, 800)
    if y - height < 52:
        raise ValueError(f'Content below footer at {y-height:.1f}: {value[:50]}')
    p.drawOn(c, x, y-height)
    return y-height


def label(value, x, y, size=9, color=GREEN):
    c.setFillColor(color)
    c.setFont('Helvetica-Bold', size)
    c.drawString(x, y, value)


def start(n, title=None):
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    label('DATACENTER TERM PROJECT', L, 747)
    c.setStrokeColor(RULE)
    c.line(L, 731, R, 731)
    c.line(L, 52, R, 52)
    label('Research-Paper Similarity Service', L, 34, 8, MUTED)
    c.setFillColor(MUTED)
    c.setFont('Helvetica', 8)
    c.drawRightString(R, 34, f'{n} / 5')
    if title:
        para(title, L, 703, size=33, leading=37, font='Times-Bold')


def section(title, value, y):
    label(title, L, y, size=13)
    return para(value, L, y-10) - 25


def line_arrow(x1, y1, x2, y2):
    from math import atan2, cos, sin

    c.setLineWidth(1.25)
    c.setStrokeColor(GREEN)
    c.line(x1, y1, x2, y2)
    angle = atan2(y2-y1, x2-x1)
    for offset in (-0.52, 0.52):
        c.line(x2, y2, x2-6*cos(angle+offset), y2-6*sin(angle+offset))


def node(x, y, w, title, subtitle):
    c.setStrokeColor(RULE)
    c.setFillColor('#FFFFFF')
    c.roundRect(x, y, w, 42, 6, fill=1, stroke=1)
    label(title, x+9, y+24, 9.1, INK)
    para(subtitle, x+9, y+19, w-15, 7.6, 9.5, color=MUTED)


start(1)
para('Research-Paper<br/>Similarity Service', L, 692, size=50, leading=51, font='Times-Bold')
label('PROJECT PARTICIPANTS', L, 564, size=9)
para('Mohadeseh Khoshnevisan and Sepehr Rezaei', L, 555, size=15, leading=20)
y = section('Project overview',
            'Researchers can paste an abstract or a short project description into a web page. '
            'The service embeds the text and ranks papers in a fixed arXiv collection. Each response '
            'contains up to ten papers with their titles, authors, arXiv links, and cosine similarity scores.', 494)
y = section('Goals',
            'Provide a working interface for finding related papers across machine learning, natural language '
            'processing, and information retrieval. Decouple request intake from CPU inference, reuse repeated '
            'results through Redis, and let other workers take over unacknowledged jobs. Measure the effect '
            'of running 1, 2, 4, or 8 replicas under the same workload.', y)
y = section('Corpus and model',
            'The evaluation corpus contains 25,000 arXiv abstracts chosen by stable ID hash from a pinned '
            '2022-2026 public metadata snapshot. Each record has at least one of cs.LG, cs.CL, or cs.IR. '
            'The repository includes the compressed corpus and its provenance. The pretrained MiniLM encoder '
            'produces 384-dimensional embeddings on CPU without model training.', y)
section('Deployment hardware',
        'The final implementation runs Docker Compose in Ubuntu 24.04 on Windows WSL2. The AMD Ryzen AI 7 445 '
        'host has 6 physical cores and 12 hardware threads. WSL exposes 12 logical CPUs and 15 GiB of memory. '
        'Each worker uses one model thread, and the stack uses local disk volumes. This deployment replaces '
        'the proposal\'s Google Compute Engine VM and Cloud Storage bucket.', y)
c.showPage()

start(2, 'Architecture and request flow')
para('The PostgreSQL job row doubles as a durable outbox entry. The dispatcher marks it published only after RabbitMQ confirms the message.', L, 647)
c.setFillColor(PALE)
c.setStrokeColor(RULE)
c.roundRect(L+86, 322, 410, 268, 8, fill=1, stroke=1)
label('SERVICE CONTAINERS ON ONE HOST', L+98, 572, 8)
node(58, 480, 75, 'Browser', 'HTTP on loopback')
node(153, 480, 111, 'FastAPI', 'Validate, submit, poll')
node(290, 480, 118, 'PostgreSQL', 'Jobs and pgvector')
node(433, 480, 110, 'Dispatcher', 'Outbox to queue')
node(433, 388, 110, 'RabbitMQ', 'Durable job messages')
node(290, 388, 118, 'Worker replicas', 'MiniLM and retrieval')
node(153, 388, 111, 'Redis', 'Cache ranked results')
node(290, 246, 142, 'Object storage', 'Shared Docker volume')
line_arrow(133, 501, 153, 501)
line_arrow(264, 501, 290, 501)
line_arrow(433, 501, 408, 501)
line_arrow(486, 480, 486, 430)
line_arrow(433, 409, 408, 409)
line_arrow(408, 397, 433, 397)
line_arrow(347, 430, 347, 480)
line_arrow(290, 409, 264, 409)
line_arrow(207, 480, 207, 430)
line_arrow(349, 388, 349, 288)
c.setStrokeColor(GREEN)
c.line(153, 489, 145, 489)
c.line(145, 489, 145, 267)
line_arrow(145, 267, 290, 267)
label('ACK', 410, 383, 7, MUTED)
label('Publish', 493, 452, 7, MUTED)
label('with confirm', 493, 442, 7, MUTED)
label('Read', 356, 340, 7, MUTED)
label('Store query text', 156, 273, 7, MUTED)
para('The API maps a loopback port on the host. PostgreSQL, RabbitMQ, and Redis stay on the Compose network.', L, 235, size=8.5, leading=11.5, color=MUTED)
y = section('Submit and retrieve',
            'The browser sends a JSON request. FastAPI checks the cache using the model, snapshot digest, and '
            'normalized text hash. On a miss it stores the text and inserts a job. A worker receives the job ID, '
            'loads the text, encodes it, and asks pgvector for the nearest papers. The worker commits the ranked '
            'results before acknowledging the delivery. The browser polls the job and renders its results.', 203)
section('Index the corpus',
        'The CLI writes the fixed snapshot and batch objects to storage. It creates index jobs in the same queue '
        'and opens query intake after the indexed row count matches the snapshot.', y)
c.showPage()

start(3, 'Component choices')
parts = [
    ('FastAPI and browser', 'FastAPI exposes a JSON REST interface and serves an HTML/JavaScript client. A job ID allows short submissions and status polling, which adds HTTP traffic while work is pending.'),
    ('RabbitMQ and dispatcher', 'A durable queue buffers bursts and hands jobs to available workers. Publisher confirms and manual acknowledgements support recovery. A separate dispatcher closes the database-to-broker publication gap at the cost of an extra process and polling.'),
    ('Python workers and MiniLM', 'Each worker reads object data and embeds it on CPU. Small batches support corpus ingestion. Each replica holds its own model in memory, and MiniLM truncates input beyond its model context.'),
    ('PostgreSQL and pgvector', 'One store holds papers, job state, and ranked results. Exact cosine search is easy to validate and returns deterministic ties by arXiv ID. Each uncached search scans the vectors, and all replicas share this database.'),
    ('Redis', 'A one-hour key-value cache gives repeat queries a fast path. The API and workers continue through PostgreSQL when Redis is unavailable. Cache eviction or restarts increase inference work.'),
    ('Local object volume', 'The shared Docker volume holds the fixed snapshot, embedding batches, and submitted text. Workers read by object key. Local disk avoids a storage service dependency, and the volume shares the host failure domain.'),
    ('Docker Compose and WSL2', 'Containers isolate dependencies and allow the worker service to scale on one Linux host. Replicas share CPU, memory, and disk. The architecture uses six datacenter component categories: JSON encoding, HTTP API, queue, database, key-value store, and containers.'),
]
y = 644
for i, (name, detail) in enumerate(parts):
    if i:
        c.setStrokeColor(RULE)
        c.line(L, y+10, R, y+10)
    label(name, L, y, 12)
    y = para(detail, L, y-8, size=10.5, leading=14.2) - 20
c.showPage()

start(4, 'Testing and fault recovery')
y = 639
y = section('Failure handling',
            'RabbitMQ requeues unacknowledged messages when a worker loses its connection. A database advisory '
            'lock serializes attempts for a job. A redelivery after a successful commit reads the terminal status '
            'and acknowledges it without computing a second result. A job can make up to three attempts. The '
            'durable queue and PostgreSQL outbox address different parts of the delivery path.', y)
y = section('Debugging and verification',
            'Use job IDs and worker hostnames to match API acceptance, dispatcher publication, worker claims, '
            'embedding and search timings, and terminal events. The API tests cover malformed inputs, body '
            'size, queue acceptance, cache responses, and an uninitialized corpus. Corpus tests compare '
            'reproducible snapshots from equivalent inputs. The ranking test compares pgvector to a NumPy '
            'cosine calculation when a test database is available.', y)
y = section('Observed results', escape(E['tests']), y)
y = section('End-to-end deployment checks', escape(E['integration']), y)
section('Retrieval quality',
        'Use a recognizable topic such as dense passage retrieval for open-domain question answering to inspect '
        'the returned papers. A cosine score is a model similarity value. Relevance across research topics '
        'would require a labeled evaluation set with measures such as recall@10 or nDCG@10.', y)
c.showPage()

start(5, 'Workload and limits')
y = section('Local benchmark method', escape(E['method']), 642)
columns = [L+9, L+164, L+224, L+289, L+354, L+417]
header = ['Configuration', 'Jobs/s', 'p50 ms', 'p95 ms', 'Failures', 'Cache hits']
c.setFillColor(GREEN)
c.roundRect(L, y-17, R-L, 22, 4, fill=1, stroke=0)
for x, value in zip(columns, header, strict=True):
    label(value, x, y-9, 8.8, '#FFFFFF')
y -= 23
for i, row in enumerate(E['runs']):
    if i % 2 == 0:
        c.setFillColor(PALE)
        c.rect(L, y-14, R-L, 18, fill=1, stroke=0)
    for x, value in zip(columns, row, strict=True):
        label(str(value), x, y-8, 8.8, INK)
    y -= 18
y = section('Observed workload', escape(E['workload']), y-18)
y = section('Bottlenecks and limits',
            'Uncached searches share CPU with inference, JSON serialization, and PostgreSQL. Exact search '
            'checks 25,000 vectors per query. The raw float32 values occupy about 38.4 MB before database '
            'overhead. Polling adds latency, and the single-host topology shares one database and broker. '
            'The API accepts up to 12,000 normalized characters, and MiniLM sees up to 256 word pieces.', y)
label('References', L, y, 13)
sources = [
    ('arXiv bulk metadata and snapshot', 'https://info.arxiv.org/help/bulk_data.html'),
    ('Pinned source dataset on Hugging Face', 'https://huggingface.co/datasets/TheDima/arxiv-cs-2022-2026/tree/7576b7717c7a9b8b0f1f9113e3b9c7ea6166c5b6'),
    ('Sentence Transformers model card', 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2'),
    ('pgvector exact cosine search', 'https://github.com/pgvector/pgvector'),
    ('RabbitMQ acknowledgements and confirms', 'https://www.rabbitmq.com/docs/confirms'),
]
for name, url in sources:
    y = para(f'<link href="{url}" color="{GREEN}">{escape(name)}</link>', L, y-5, size=9.3, leading=11.5)
c.showPage()
c.save()
print(OUT)
