const form = document.querySelector("#query-form");
const query = document.querySelector("#query");
const submit = document.querySelector("#submit");
const statusLine = document.querySelector("#status");
const panel = document.querySelector("#result-panel");
const results = document.querySelector("#results");

function countCharacters() {
  document.querySelector("#count").textContent = `${query.value.length.toLocaleString()} / 12,000`;
}

query.addEventListener("input", countCharacters);
document.querySelector("#example").addEventListener("click", () => {
  query.value = "I am looking for neural information retrieval methods that use a dual encoder to embed queries and passages, with dense vector search for open-domain question answering.";
  countCharacters();
  query.focus();
});

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
  return data;
}

function showResults(papers) {
  results.replaceChildren();
  papers.forEach((paper, index) => {
    const row = document.createElement("li");
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = index + 1;
    const details = document.createElement("div");
    const title = document.createElement("a");
    title.href = paper.url;
    title.textContent = paper.title;
    title.target = "_blank";
    title.rel = "noopener noreferrer";
    const authors = document.createElement("p");
    authors.textContent = paper.authors;
    details.append(title, authors);
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = Number(paper.score).toFixed(3);
    row.append(rank, details, score);
    results.append(row);
  });
  panel.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  panel.hidden = true;
  statusLine.dataset.error = "false";
  statusLine.textContent = "Submitting query…";
  try {
    let job = await request("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: query.value }),
    });
    const end = Date.now() + 120000;
    while (job.status === "pending" || job.status === "processing") {
      statusLine.textContent = `${job.status === "pending" ? "Queued" : "Searching"} · ${job.job_id}`;
      if (Date.now() >= end) throw new Error(`Search is still running. Job ID ${job.job_id}`);
      await new Promise(resolve => setTimeout(resolve, 600));
      job = await request(`/jobs/${job.job_id}`);
    }
    if (job.status === "failed") throw new Error(job.error || "The search failed.");
    showResults(job.results);
    statusLine.textContent = job.cache_hit ? "Served from Redis cache" : `Search completed · ${job.job_id}`;
  } catch (error) {
    statusLine.dataset.error = "true";
    statusLine.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

request("/healthz").then(info => {
  const corpus = document.querySelector("#corpus");
  if (info.papers) corpus.textContent = `${info.papers.toLocaleString()} indexed arXiv papers${info.model === "smoke" ? " · smoke mode" : ""}`;
  else corpus.textContent = "arXiv corpus is initializing";
}).catch(() => {});
