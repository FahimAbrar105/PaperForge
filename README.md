# Paper Forge

Paper Forge turns your paper into a submission-ready version for a computer-science venue. You upload your
manuscript (LaTeX, Markdown or Word), your `.bib` file and your figures, pick a venue and an agentic mode, and
get back:

1. **A formatted PDF** built with the venue's official LaTeX template.
2. **A LaTeX source ZIP** you can keep editing or upload to Overleaf.
3. **A compliance report** that lists what passed, what is a warning, what failed and what you still need to
   check by hand.

It runs on your own computer and works offline after the first start. With a free Gemini key you can run it
**fully agentic**: AI agents structure the paper, plan the layout, repair LaTeX errors and review the result,
switching to built-in rules automatically if the AI limit is reached. Without a key it runs on rules alone. PDF
papers are not accepted; upload the source.

Supported venues, each with its official, unmodified template:

| Venue | Template | Paper | Main-text pages |
|---|---|---|---|
| **IEEE Conference** | IEEEtran (two columns) | US Letter | 6 (8 at most) |
| **ACL** (also EMNLP, NAACL and other ACL Rolling Review venues) | acl.sty (two columns) | A4 | 8, camera-ready 9 |
| **ICLR** | iclr2027_conference.sty (one column) | US Letter | 9, camera-ready 10 |
| **CVPR** | cvpr.sty (two columns) | US Letter | 8 |
| **ACM Conference** | acmart, sigconf format (two columns) | US Letter | set by each conference |

ACL, ICLR, CVPR and ACM have double-blind review, so the upload page asks for the version: **Anonymous
submission** (names, emails and acknowledgements hidden, review line numbers on) or **Camera-ready** (authors
shown, plus any extra page the venue allows).

For full step-by-step installation, disk usage and every option, see **[SETUP.md](SETUP.md)**.

---

## 1. What you need installed

| Your computer | What you need |
|---|---|
| **Windows 10/11** | **Nothing.** `run.bat` downloads a private copy of Python and the Tectonic LaTeX compiler *into this folder*. |
| **macOS / Linux** | **Python 3.11+** (lightest) **or Docker**. `run.sh` picks whichever you have. |
| Any, if you prefer containers | **Docker** (Docker Desktop on Windows/macOS). |

You do **not** need to install LaTeX, Node.js or any AI software.

## 2. How to run it

**Windows:** double-click `run.bat` (or run it from a terminal).
The first start downloads about 100 MB into the `runtime` folder and prepares the LaTeX package cache; after
that it starts in seconds and works offline. Your browser opens **http://localhost:8000**.
Keep the black window open while you use Paper Forge; close it (or press Ctrl+C) to stop.

**macOS / Linux:**

```bash
chmod +x run.sh      # first time only
./run.sh             # Python 3.11+ found -> local mode; otherwise Docker
```

Then open **http://localhost:8000**.

**Docker (any system):** `run.bat docker` on Windows, `./run.sh docker` on macOS/Linux, or simply
`docker compose up -d --build`. Stop it with `docker compose down`.

**Share it:** `run.bat zip` (or `./run.sh zip`) writes `paper-forge.zip` next to this folder, without your
settings, API key, jobs or the downloaded runtime. See SETUP.md, section 8, also for putting it on GitHub.

## 3. Try the sample paper

The `sample_paper` folder holds the same short (fictional) paper three ways:

- `sample_paper/latex/`: upload `paper.tex`, `references.bib` and both images in `figures/`.
- `sample_paper/markdown/`: upload `paper.md`, `references.bib` and both images in `figures/`.
- `sample_paper/docx/`: upload `paper.docx`.

Choose a venue (for example **IEEE Conference**), click **Format paper**, and watch the workflow log. When it finishes, download the
PDF, the LaTeX ZIP and the report. To see the repair loop in action, upload the LaTeX version **without** its
figures: you still get a PDF, with placeholder boxes, and the report marks the figures as failed.

## 4. Agentic modes and the Gemini key (free tier)

On the upload page you choose how much AI to use for each paper:

- **Full agentic**: AI agents run the Content Structurer, LaTeX Formatter, QA & Repair and Report steps. File
  safety checks and venue rules stay rule-based, and Tectonic compiles. If the AI limit is reached, the remaining
  steps switch to rules automatically and the job is marked *partly agentic*.
- **Partial**: rules do the work; AI only for hard cases (at most 3 requests).
- **Off**: rules only, fully offline. This is the default until you add a key.

To turn on Full or Partial:

1. Create a free key at <https://aistudio.google.com/apikey> (your own Google account; not a paid subscription).
2. In Paper Forge open **Settings**, keep **Gemini** as the provider, paste the key, pick the default agentic
   mode, click **Save settings**, then **Test Gemini**.

A typical paper uses 3 to 8 requests in Full mode (limit per paper: 12, adjustable); a clean paper needs 3, a
broken one more. Requests are spaced a few seconds apart to respect the free tier, and everything an agent returns
is checked against your paper before it is used. The compliance report shows which steps used AI and which Gemini
model answered.

Settings lists the Gemini models your key can use, as Google reports them, and the one you pick is asked first.
The default is `gemini-flash-latest`, Google's name for its current Flash model. Free keys have per-minute and
per-day limits that differ by model and can change (see Google's
[rate limits page](https://ai.google.dev/gemini-api/docs/rate-limits)), Google retires old models, and its newest
models are often busy. So when the chosen model is busy, retired or out of quota, Paper Forge steps down to the next
Flash or Flash-Lite model your key can use, then tries the others, and skips a model whose daily quota is used up
until the next day. The job log says when it switches. A free-tier answer takes from a few seconds to about a
minute, so a Full-mode paper can take a few minutes; the job page shows a working indicator meanwhile.

Under Google's terms for free use, what you send may be used to improve Google's products and may be read by human
reviewers. For a paper that must stay confidential, use Off mode, Ollama, or a key with billing turned on.

## 5. Optional: Ollama (local AI)

1. Install Ollama from <https://ollama.com> and pull a small model, for example `ollama pull llama3.2:3b`.
2. In **Settings**, either choose **Ollama** as the provider, or keep Gemini and tick **Use Ollama when Gemini
   is unavailable or out of quota**. The default server URL is `http://localhost:11434`. Click **Test Ollama**.

No GPU is required, but small models on a CPU can take a minute per request, and Ollama stores its models on C:
by default.

## 6. What stays local

- Uploads, generated files, job history (SQLite) and settings live in the **`output`** folder on your computer.
- The Gemini key is stored only in `output/settings.json` and is never shown again in the browser or in logs.
- Nothing is uploaded anywhere, **except** in Full or Partial mode with Gemini: then text of the paper, a summary
  of its figures and tables, short LaTeX excerpts around errors and the check results are sent to Google's Gemini
  API. Your files themselves are never sent. Ollama runs on your machine.
- The server listens only on this computer (`127.0.0.1`).
- Old jobs are deleted after 7 days by default (change it in Settings; 0 keeps everything).

## 7. Add a new venue later

No Python changes are needed for a typical venue (for example NeurIPS, ICML or AAAI, whose official kits you
download by hand from the venue's website):

1. Create `templates/<venue_id>/` with the venue's official `.cls`/`.sty`/`.bst` files and a `main.tex.j2`
   (copy the `main.tex.j2` of the closest bundled venue and adapt the front matter).
2. Create `venue_rules/<venue_id>.json` (copy the closest file in `venue_rules/`): template files, paper size,
   columns, page limits, required sections, forbidden packages, and which checks to run.
3. Restart Paper Forge. The venue appears in the dropdown automatically.

A brand-new kind of check is one small function registered in `app/validators/` (see `registry.py`).
Details: [SETUP.md, "Adding a venue"](SETUP.md#9-adding-a-new-venue).

## 8. Troubleshooting

| Problem | What to do |
|---|---|
| **Windows: "curl.exe / tar.exe not found"** | You need Windows 10 (version 1803) or newer. |
| **First start fails while downloading** | Check your internet connection, then run `run.bat` again; it continues where it stopped. `run.bat reset` starts clean. |
| **"Port 8000 is busy"** | Start on another port: `set PAPERFORGE_PORT=8001 && run.bat` (Windows) or `PAPERFORGE_PORT=8001 ./run.sh`. |
| **Docker: "Docker is not running"** | Start Docker Desktop and wait until it says it is running. |
| **Docker on Linux: cannot write to `output`** | Run `sudo chown -R 1000 output` once (the container runs as user 1000). |
| **Tectonic: "not in the cache" / download errors** | The first compile of a new LaTeX package needs internet once. Paper Forge retries with downloads allowed automatically. |
| **Tectonic not found** | Start Paper Forge with `run.bat`/`run.sh` (they install it), or rebuild the Docker image. |
| **PDF missing, report says compilation failed** | Download the LaTeX ZIP and read the "Failed checks" in the report: they quote the LaTeX error and line. |
| **Gemini: "rate limit reached" / "daily quota used up"** | Free keys have per-minute and per-day limits for each model. Paper Forge tries the other Flash models first; when all are used up, the job switches to rules (or Ollama) and is marked partly agentic. Try again the next day. |
| **"Agentic mode needs an AI provider"** | Add a Gemini key in Settings, or choose Off on the upload page. |
| **Gemini: "rejected the API key"** | Re-paste the key in Settings and click Test Gemini. |
| **Ollama: "not reachable" / "model not installed"** | Start Ollama, check the URL, and run `ollama pull <model>`. |

More fixes are in [SETUP.md](SETUP.md#11-troubleshooting).

## License

Paper Forge is MIT licensed (see `LICENSE`). The bundled IEEEtran files are LPPL 1.3
(`templates/ieee_conference/LICENSE-IEEEtran.txt`).
