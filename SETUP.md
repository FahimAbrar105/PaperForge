# Paper Forge: complete setup guide

This guide is for anyone installing, moving, sharing or maintaining Paper Forge. The short version is in
[README.md](README.md).

## Contents

1. [What gets installed, where, and how big it is](#1-what-gets-installed-where-and-how-big-it-is)
2. [Windows (portable, recommended)](#2-windows-portable-recommended)
3. [macOS and Linux](#3-macos-and-linux)
4. [Docker (any system)](#4-docker-any-system)
5. [Using Paper Forge](#5-using-paper-forge)
6. [Agentic modes: Full, Partial, Off](#6-agentic-modes-full-partial-off)
7. [Configuration reference](#7-configuration-reference)
8. [Sharing, moving, updating, uninstalling](#8-sharing-moving-updating-uninstalling)
9. [Adding a new venue](#9-adding-a-new-venue)
10. [Running the tests](#10-running-the-tests)
11. [Troubleshooting](#11-troubleshooting)
12. [Folder layout](#12-folder-layout)

---

## 1. What gets installed, where, and how big it is

Paper Forge never installs anything system-wide in portable/local mode. Everything it downloads goes into the
`runtime` folder **inside the Paper Forge folder**, and all your data goes into the `output` folder.

| Item | Downloaded from | Stored in | Approx. size |
|---|---|---|---|
| Python 3.12.10 embeddable (Windows only) | python.org | `runtime\python` | 11 MB download, ~20 MB on disk |
| pip (Windows only) | bootstrap.pypa.io | `runtime\python` | ~10 MB |
| Python packages: FastAPI, Uvicorn, Pydantic, python-multipart, Jinja2, python-docx, PyMuPDF, bibtexparser (+ their dependencies) | pypi.org | `runtime\python\Lib\site-packages` (Windows) or `runtime/venv` (macOS/Linux) | ~30 MB download, ~110 MB on disk |
| Tectonic 0.15.0 LaTeX compiler | github.com (official releases) | `runtime/tectonic` | ~20 MB download, ~50 MB on disk |
| LaTeX packages for the IEEE template (fetched by Tectonic on first use) | Tectonic's bundle server (relay.fullyjustified.net) | `runtime/tectonic-cache` | ~50-150 MB |
| Temporary files during setup | none | `runtime/tmp` | small, reusable |

**Total: roughly 250-350 MB, all inside the Paper Forge folder.** Nothing is written to `C:\` (Windows) or your
home folder in portable/local mode: `run.bat` points `TEMP`, `TMP`, the pip cache and the Tectonic cache at
`runtime\`.

Exceptions you should know about:

- **Docker mode** stores images inside Docker's own storage (on Windows/macOS that is Docker Desktop's disk
  image, which is on `C:` by default unless you move it in Docker Desktop > Settings > Resources). The image is
  about 600-700 MB.
- **Ollama**, if you choose to install it, is a separate program with its own install location and model folder.
- Your **browser** caches the Paper Forge web page like any website.

---

## 2. Windows (portable, recommended)

**Requirements:** Windows 10 version 1803 or newer, or Windows 11 (these include `curl.exe` and `tar.exe`).
Internet for the first start only. About 350 MB of free space on the drive where the folder lives.

1. Put the `paper-forge` folder wherever you like, for example `D:\paper-forge`.
   Avoid folder names containing `&`, `!` or `%`.
2. Double-click **`run.bat`** (or open Command Prompt in the folder and type `run.bat`).
3. The first start shows four steps:
   - `[1/4]` downloads private Python,
   - `[2/4]` sets up pip,
   - `[3/4]` installs the Python packages,
   - `[4/4]` downloads Tectonic,
   - then *"Preparing the LaTeX package cache"* formats the sample paper once so the IEEE LaTeX packages are
     cached for offline use. This takes a few minutes.
4. Your browser opens **http://localhost:8000**. If it does not, open that address yourself.
5. Keep the window open while you work. Press **Ctrl+C** or close the window to stop Paper Forge.

Later starts skip all downloads and take a few seconds; they work without internet.

**Other commands**

| Command | What it does |
|---|---|
| `run.bat` | Start in portable mode. |
| `run.bat docker` | Start with Docker Desktop instead (if you have it). |
| `run.bat reset` | Delete `runtime\` (Python, Tectonic, caches). Your jobs in `output\` are kept. |
| `set PAPERFORGE_PORT=8001 && run.bat` | Use another port. |

Windows SmartScreen may warn the first time you run a `.bat` file from the internet: choose
*More info > Run anyway* if you trust the source.

---

## 3. macOS and Linux

**Requirements:** Python 3.11 or newer (`python3 --version`) **or** Docker. `curl` and `tar` (preinstalled on
macOS and most Linux distributions). Internet for the first start.

```bash
cd paper-forge
chmod +x run.sh        # first time only
./run.sh               # local mode if Python 3.11+ exists, otherwise Docker
```

Local mode creates `runtime/venv` (private virtual environment), downloads Tectonic into `runtime/tectonic`
(Linux x86_64/arm64, macOS Intel/Apple Silicon), warms the LaTeX cache, and starts the server on
**http://localhost:8000**. If you already have `tectonic` on your PATH it is reused.

| Command | What it does |
|---|---|
| `./run.sh` | Automatic choice (local, else Docker). |
| `./run.sh local` | Force local mode. |
| `./run.sh docker` | Force Docker mode. |
| `./run.sh reset` | Delete `runtime/`; jobs in `output/` are kept. |
| `PAPERFORGE_PORT=8001 ./run.sh` | Use another port. |

On macOS, if Python is missing, install it from python.org or with Homebrew (`brew install python@3.12`).
If you installed Python from python.org on macOS, also run *Install Certificates.command* once (in the Python
folder under Applications); without it Gemini requests fail with "Gemini unreachable".
On Debian/Ubuntu, Python's `venv` module is a separate package: `sudo apt install python3-venv`.

---

## 4. Docker (any system)

**Requirements:** Docker Desktop (Windows/macOS) or Docker Engine with the compose plugin (Linux).

```bash
docker compose up -d --build     # or: run.bat docker / ./run.sh docker
```

- The first build downloads the Python base image, Tectonic and the LaTeX packages, and compiles the sample paper
  inside the image so later compiles work offline. Expect a few minutes.
- Open **http://localhost:8000**. The port is bound to `127.0.0.1`, so other computers cannot reach it.
- Your data is in the `output` folder next to `docker-compose.yml` (mounted into the container).
- Stop: `docker compose down`. Logs: `docker compose logs -f`.
- Change retention: edit `PAPERFORGE_RETENTION_DAYS` in `docker-compose.yml`.

---

## 5. Using Paper Forge

1. Choose the **target venue**: *IEEE Conference*, *ACL / ARR*, *ICLR*, *CVPR* or *ACM (sigconf)*. For a
   double-blind venue, also choose *Anonymous submission* (the review version) or *Camera-ready* (the final
   version with authors).
2. Drop or pick your files:
   - one manuscript: `.tex` (plus any `\input` files), `.md` or `.docx` (PDF papers are not accepted);
   - your `.bib` file(s);
   - figures: `.png`, `.jpg`, `.pdf`, `.svg` (converted automatically) or `.eps` (must be converted to PDF/PNG
     first; Paper Forge flags it).
   Upload figures flat; folder names in `\includegraphics{figures/x}` are matched by file name.
3. Pick the **agentic mode** (Full, Partial or Off; see section 6) and click **Format paper**. The job page
   shows each step live:
   Upload Handler > Venue Analyst > Content Structurer > LaTeX Formatter > Compiler <> QA & Repair (up to 5
   passes) > Report Generator.
4. Download the **PDF**, the **LaTeX ZIP** and the **compliance report** (HTML; JSON and Markdown copies are in
   the job folder). You can **cancel** a running job. Job history survives restarts.

**Which input works best?** LaTeX and Markdown give the most faithful results. Word files work well when you use
Word's *Title* and *Heading 1/2* styles. PDF papers are not accepted, because equations, tables and layout cannot
be recovered from a PDF reliably; upload the source instead. A `.pdf` file is accepted as a figure.

**Markdown conventions:** YAML front matter (`title`, `author` list with `name`/`affiliation`/`email`,
`abstract`, `keywords`, `bibliography`), `[@key]` citations, `![caption](file.png){#fig:label}` figures,
pipe tables followed by `Table: caption {#tbl:label}`, `$...$` and `$$...$$` math, `@fig:label` references.
See `sample_paper/markdown/paper.md`.

**What the report means:**
- *Passed*: an automated check succeeded.
- *Warnings*: the PDF is fine but something should be improved (for example text sticking into the margin, or an
  anonymous version that links to your GitHub page).
- *Failed*: a venue rule is broken (for example over the page limit, missing figure, citation without entry).
- *Changes Paper Forge made*: each small correction it made to your text, and where (see below).
- *Style suggestions*: points from the venue's author guidelines for you to decide, for example a heading with a
  single subheading, an abbreviation never spelled out, or a reference without its DOI. They never change the
  overall result.
- *Manual review*: things a program cannot verify (copyright notice, PDF eXpress, figure legibility...).
- The overall result says *Layout checks passed* only when there are no failures and no warnings.

**Corrections Paper Forge makes itself.** In every agentic mode and without an AI key, Paper Forge makes the small
corrections the venue's guidelines agree on, and lists each one in the job log and in the report's *Changes Paper
Forge made* (what changed and where):

| Correction | IEEE | ACL | ICLR | CVPR | ACM |
|---|---|---|---|---|---|
| A display equation ends with the comma or period its sentence needs | yes | yes | yes | yes | yes |
| Equations, mid-sentence / at a sentence start | "(2)" / "Equation (2)" | "Equation (2)" | "Eq. (2)" / "Equation (2)" | "Eq. (2)" / "Equation (2)" | "Eq. (2)" / "Equation (2)" |
| Figures, tables, sections | "Fig. 1", "Table I", "Section II" (also a typed "Table 1" or "Section 2.1") | "Figure 1", "Table 1", "Section 1" | left as you wrote them | "Fig. 1", "Tab. 1", "Sec. 1" (spelled out at a sentence start) | left as you wrote them |
| Table captions | above | below | above | above | above |
| A sentence that starts with a citation number | "Reference [3] shows" | | | | |
| Author-year citation used as the subject ("(Lee, 2020) shows") | | "Lee (2020) shows" | "Lee (2020) shows" | | |
| Keywords (Index Terms) in alphabetical order | yes | | | | |
| "0.25", not ".25" | yes | | | | |

On every venue, figure captions go below the figure, footnote marks go after a period or comma ("traffic.^1"),
"et. al." and "et al" become "et al.", and the anonymous version leaves out the acknowledgements. `\cref` and
`\autoref` are written out in the venue's words when its class does not define them the same way (CVPR keeps
`\cref`), and abbreviation macros from the CVPR kit (`\eg`, `\etal`, ...) are spelled out for the other venues.
In an author-year venue, "Lee et al. (Lee et al., 2020)" becomes "Lee et al. (2020)"; in IEEE, `\citet{lee20}`
keeps the names it prints ("Lee et al. [3]"). The abstract gets the "et al." and "0.25" corrections too. Code,
file names, URLs, labels and `\texttt` text are never changed, and an equation inside a figure gets no
punctuation. When the words around an equation or a reference don't make the right form clear, Paper Forge
leaves it alone (IEEE's "the equations (1)--(3)" stays, since "the (1)--(3)" would not read). Paper Forge
never changes your claims, numbers or references. These choices live in each venue's file in `venue_rules/`
(`content_rules`), and `docs/VENUE_GUIDELINES.md` lists the official guideline each one comes from.

**What Paper Forge tells you to fix yourself.** Everything else the venue's guidelines ask for is checked and
listed in the report, with the exact places (where it can find them) and how to fix it:
- *Every venue*: page limit, paper size, fonts, required sections, abstract length, figures, citations and
  references that resolve, text in the margin, abbreviations never spelled out, plain underscores, British and
  American spelling mixed, low-resolution images, a typed "Fig. 3" or "Table 4" the paper does not have, figures
  or tables without a caption, leftover notes (`\todo`, TODO, FIXME), and in the anonymous version anything that
  gives away the authors (self-references such as "our previous work", personal links, emails, grants, a
  `\thanks` note under the title).
- *IEEE*: a heading with a single subheading, citation numbers used as words, references without the
  conference city and country, journal month or full author list, abstract of 150 to 250 words in one paragraph
  without math, citations or footnotes, title case without "new" or "novel", headings in title case,
  affiliations without city and country, British spellings (IEEE uses American), `eqnarray`, "10ms" instead of
  "10 ms", images under 300 dpi, a title in capitals, citations typed as "(Smith et al., 2020)".
- *ACL*: the required Limitations section, an abstract of at most 200 words in plain text, a title in title case
  (not capitals), references without a DOI or ACL Anthology link or with initials only, arXiv preprints that may
  have a published version, affiliations without a full address (final version).
- *ICLR*: the required AI use statement, an abstract of one paragraph, the recommended ethics and
  reproducibility statements.
- *CVPR*: headings in sentence case and at most two levels, every displayed equation numbered (also `$$...$$`),
  a title in capitals, appendices in the supplementary material, no links at all in the review version, references with initials only, arXiv preprints.
- *ACM*: a `\Description` for every figure, CCS concepts (final version), an abstract of at most two paragraphs,
  title style (no capitals, no forced line breaks), references without DOIs or with initials only, affiliations with institution, city and country,
  and no `\newcommand` in the final version (ACM's production system rejects it).

Paper Forge never invents content: it does not add citations, results, author names or text. Missing figures
become visible placeholder boxes, and citations without a bibliography entry are removed and listed as failed.

**Paper Forge Assistant (help with what is left to fix).** When a job has finished and has a report (completed,
or failed with a report), the job page shows the *Paper Forge Assistant* under the downloads. It lists every open
issue from the report (failed checks, warnings, style suggestions and manual-review items; not passed checks and
not the changes Paper Forge already made), each with a **Help me fix this** button, and has a box for any question
about your paper and the venue's guidelines.

- **Without an AI key** the assistant answers from Paper Forge's own rules: the check's message and details, the
  venue's rule and a short "how to fix" for that kind of check. A question typed in the box gets a short answer
  saying what the assistant can do without a key, the list of open issues, and how to add a key. Nothing leaves
  your computer.
- **With your Gemini key** (or Ollama, if you chose it in Settings) the assistant answers in its own words. Each
  question is one AI request. It does not count toward the per-paper AI limit, and it works whatever the default
  agentic mode is. The answer may include *suggested text* in a block with a **Copy** button: check it, then paste
  it into your own source.
- After **Help me fix this**, follow-up questions stay about that issue ("Asking about: ..."); press × to ask
  about the whole paper again.
- **The assistant only advises.** It never changes your paper: you edit your own source and upload it again.
  It must not change your claims, numbers, results or references. A suggested text that adds, drops or changes a
  number (or its unit or order), adds or drops a citation, or turns a claim around ("reduces" into "increases")
  compared with the passage it rewrites is left out (the explanation stays, with one line saying why). Suggested
  text comes in your source's format: LaTeX, Markdown, or plain text for Word.
- If the AI is busy, rate-limited or out of its daily quota, you get the built-in answer and one line saying why.
- The conversation is saved with the job (`output/jobs/<job id>/final/chat.json`), so it is there when you open
  the job again. It is deleted with the job (Delete button or retention). *Clear conversation* empties it.
- Limits: a question can be up to 2000 characters; the newest 200 messages of a job are kept.

---

## 6. Agentic modes: Full, Partial, Off

Each paper runs in one of three modes, chosen on the upload page (the default is set in Settings):

| Mode | What happens | Needs |
|---|---|---|
| **Full agentic** | AI agents drive every step that can use one (table below). If the AI limit is reached, the remaining steps switch to rules automatically and the job is marked *partly agentic*. | An AI provider |
| **Partial** | Rules do the work. AI is asked only for a Word file the parser cannot read well, or a LaTeX error no rule understands. At most 3 requests. | An AI provider |
| **Off** (default) | Rules only. Fully offline; no AI service is contacted. | Nothing |

What each step does in Full mode:

| Step | Done by | In Full mode |
|---|---|---|
| Upload Handler | Rules, always | File type, size and content checks stay rule-based for safety. |
| Venue Analyst | Rules, always | Venue rules come from the verified venue file, never from an AI. |
| Content Structurer | AI agent | Reviews the parser's draft against your text and corrects title, authors, affiliations, abstract, keywords and Word heading levels; builds the outline of a Word file the parser could not read. |
| LaTeX Formatter | AI agent | Plans the layout: which figures and tables span both columns, which extra packages to drop; lists layout problems for you. The LaTeX itself is produced from the venue template. |
| Compiler | Tectonic tool | Compiles the LaTeX. |
| QA & Repair | AI agent | On every compile pass with problems, reads the errors and picks repair tools (add or remove a package, placeholder for a missing figure, scale a wide table, small line patch...). |
| Report Generator | AI agent | Writes a short review and the most important next steps for you. Check results always come from the rule checks. |

A typical paper uses 3 to 8 AI requests in Full mode (3 for a clean paper, more when repairs are needed). The
limit per paper is set in Settings (default 12, maximum 30). The job log and the report name the Gemini model that
answered.

**Safety, in every mode:** identical requests are cached; everything an agent returns is checked before use (text
not found in your upload is discarded, ids and package names must exist in your paper, forbidden packages are
refused, and LaTeX patches that would delete your words are rejected). The compliance report has a
"Who did each step" table, so you can see which steps used AI and why any step switched to rules.

**When the limit is hit:** free Gemini keys have per-minute and per-day limits that differ by model and can change
(see <https://ai.google.dev/gemini-api/docs/rate-limits>). Paper Forge spaces requests a few seconds apart. The model
chosen in Settings is asked first. A model that is busy, retired or out of its daily quota is replaced by the next
Flash or Flash-Lite model below it that the key can use, then by the others, and the job log says so; a model out of
quota is skipped until the next day. When every model is busy or says "wait N seconds" (up to 40), Paper Forge waits and asks again, up to
twice; if they are still busy, only that step uses rules. If every model is used up or the per-paper limit is
reached, the job continues on rules (or on Ollama, if you enabled it as a fallback, which
keeps the job fully agentic).

**Gemini (free tier, your own key):**
1. Get a key at <https://aistudio.google.com/apikey>.
2. Settings > *AI provider: Gemini* > paste key > *Save settings* > *Test Gemini*. Choose the default agentic mode
   on the same page.
3. The key is stored in `output/settings.json` only, sent only to `generativelanguage.googleapis.com` in a request
   header, and masked everywhere in the UI and logs.
4. What is sent: text of the paper (for structuring), a short summary of its figures, tables and packages (for the
   layout plan), a ~25-line excerpt of the generated LaTeX around an error (for repairs) and the list of check
   results (for the review). Uploaded files are never sent as files. Only when you ask the Paper Forge
   Assistant something: your question, the issue it is about, the venue's rules, the last few messages of that
   conversation and a short excerpt (at most about 2,500 characters) of the generated LaTeX or `.bib` entries the
   issue points to. With Ollama, all of this stays on your computer.
5. If Gemini is rate-limited, offline, or rejects the key, the job continues with Ollama (if enabled) or with rules.

You can also provide the key through the environment variable `PAPERFORGE_GEMINI_API_KEY`.

**Ollama (local):**
1. Install from <https://ollama.com>, then `ollama pull llama3.2:3b` (about 2 GB; any model works).
2. Settings > either choose *AI provider: Ollama*, or keep Gemini and tick *Use Ollama when Gemini is unavailable
   or out of quota*. Default URL `http://localhost:11434`.
3. *Test Ollama*. No GPU required.

---

## 7. Configuration reference

Environment variables (set them before `run.bat`/`run.sh`, or in `docker-compose.yml`):

| Variable | Default | Meaning |
|---|---|---|
| `PAPERFORGE_PORT` | `8000` | Web server port. |
| `PAPERFORGE_HOST` | `127.0.0.1` (`0.0.0.0` inside Docker) | Listen address. |
| `PAPERFORGE_DATA_DIR` | `<folder>/output` | Where jobs, database and settings are stored. |
| `PAPERFORGE_MAX_FILE_MB` | `20` | Per-file upload limit. |
| `PAPERFORGE_MAX_TOTAL_MB` | `50` | Total upload limit per job. |
| `PAPERFORGE_MAX_FILES` | `40` | Files per job. |
| `PAPERFORGE_RETENTION_DAYS` | `7` | Delete finished jobs older than this (`0` = keep). Settings page overrides it. |
| `PAPERFORGE_MAX_ITERATIONS` | `5` | Compile-and-repair passes (maximum 5). |
| `PAPERFORGE_COMPILE_TIMEOUT` | `180` | Seconds before a compile is stopped. |
| `PAPERFORGE_MAX_AI_CALLS` | `3` | AI requests per job in Partial mode (maximum 3). Full mode uses the limit in Settings. |
| `PAPERFORGE_GEMINI_MIN_INTERVAL` | `4` | Seconds between Gemini requests, to stay under the free tier's per-minute limit. |
| `PAPERFORGE_WORKERS` | `2` | Jobs processed at the same time. |
| `PAPERFORGE_TECTONIC` | auto | Path to the Tectonic executable. |
| `TECTONIC_CACHE_DIR` | `<folder>/runtime/tectonic-cache` | Tectonic package cache. |
| `PAPERFORGE_GEMINI_API_KEY` | empty | Gemini key if none is saved in Settings. |

Settings saved in the web page live in `output/settings.json`.

---

## 8. Sharing, moving, updating, uninstalling

**Share with someone else:** run `run.bat zip` (or `./run.sh zip`). It writes `paper-forge.zip` next to the
`paper-forge` folder (about 1 MB) with everything except `runtime/` and `output/`, so your settings, API key and
jobs stay with you. Send that file; the recipient unzips it and starts `run.bat` / `run.sh`, which downloads
their own Python and Tectonic, and they add their own Gemini key in Settings if they want the AI modes.

**Put it on GitHub:** `.gitignore` already leaves out `runtime/`, `output/` (except `output/.gitkeep`), caches and
editor folders, so `git add -A` in the `paper-forge` folder picks up only the program: `app/`, `templates/`,
`venue_rules/`, `sample_paper/`, `scripts/`, `vendor/`, `docs/`, the launchers, `requirements*.txt`, the Docker
files, `README.md`, `SETUP.md`, `LICENSE` and the dot-files. Your API key never leaves `output/settings.json`.

**Move the folder:** stop Paper Forge, move the folder, start it again. Portable mode uses relative paths.
On macOS/Linux, run `./run.sh reset` after moving (virtual environments contain absolute paths).

**Update Paper Forge:** replace the program files (keep `output/`, optionally keep `runtime/`). If
`requirements.txt` changed, the launcher reinstalls packages automatically on the next start.

**Uninstall:** stop Paper Forge and delete the folder. For Docker, also run `docker compose down --rmi local`.

**Back up your work:** copy the `output` folder.

---

## 9. Adding a new venue

Each venue is data, not code:

```
templates/<venue_id>/          official class/style files + main.tex.j2 (+ optional section.tex.j2)
venue_rules/<venue_id>.json    layout, content rules and the list of checks
```

1. **Template folder.** Copy the venue's official files (for example `acl.sty`, `acl_natbib.bst`) unmodified, and
   write down where they came from in `SOURCE.txt`. Copy the `main.tex.j2` of the bundled venue closest to yours
   (`acl`, `iclr`, `cvpr`, `acm_sigconf` or `ieee_conference`) and adapt the preamble and the title/author block.
   The template uses Jinja2 with LaTeX-safe delimiters: `\VAR{title}`, `\BLOCK{ for a in authors }...\BLOCK{ endfor }`.
   Available variables:
   - `title`; `bare_title` and `title_notes` (the title without its `\thanks{}` notes, and the notes), and
     `pdf_title` (plain text for PDF metadata);
   - `authors`, each with `name`, `email`, `affiliations`, `affiliation_lines` (affiliations then email) and
     `marks` (numbers into `affiliations`, the shared list for venues that number affiliations);
   - `review` (true for the anonymous submission version: the authors are already replaced by a placeholder);
   - `abstract`, `keywords`, `body_chunks`, `appendix_chunks`, `acknowledgments` (empty in review mode),
     `bibliography_file`, `bibliography_style`, `thebibliography`, `extra_packages`, `macros`,
     `document_class`, `class_options`, `venue_name`.
2. **Rules file.** Copy the closest `venue_rules/<venue>.json` to `venue_rules/<venue_id>.json` and edit:
   - `template`: directory, `document_class`, `class_options`, `files` to copy, `bibliography_style`,
     `split_sections`, `citations` (`cite`, `natbib_numbers` or `natbib_author_year`), `loads_packages` (packages
     the venue's style already loads, so the paper's own `\usepackage` lines for them are dropped) and
     `caption_setup` (lines added when the paper loads `caption` or `subcaption`);
   - `layout`: `paper_size` (`letter`/`a4`), `columns`, `page_limit` (`max_pages_main`, `max_pages_total`,
     `camera_ready_extra_pages`);
   - `content_rules`: abstract word limit, keywords (`printed: false` when the venue has none), required sections,
     allowed/forbidden packages, `anonymous_submission` (double-blind venues; the upload page then offers
     *Anonymous submission* or *Camera-ready*), and the automatic corrections: `reference_words` (how equations,
     figures, tables, sections and citations are named, as [inside a sentence, at its start]; a kind left out is
     not changed), `table_caption` (`above`/`below`), `sort_keywords`, `leading_zero` and `roman_numbers`;
   - `checks`: which checks run and their severity (`error` = failed, `warning`, `style` = a suggestion that never
     changes the result, `manual`). Available check types: `compile_success`, `page_limit`, `paper_size`,
     `fonts_embedded`, `document_class`, `forbidden_packages`, `required_sections`, `abstract_length`,
     `keywords_present`, `figures_resolved`, `citations_resolved`, `references_resolved`, `overfull_boxes`,
     `missing_glyphs`, `bibliography_present`, `anonymity`, `manual`, and the writing checks
     `lone_subsection`, `citation_as_noun`, `reference_details`, `undefined_abbreviations`, `stray_underscores`,
     `abstract_min_length`, `abstract_form`, `affiliation_location`, `spelling_consistency`, `identifying_text`,
     `figure_descriptions`, `ccs_concepts`, `no_appendices`, `figure_resolution`, `title_style`, `heading_case`,
     `numbered_equations` and `text_pattern` (a rule written as a regular expression in the venue file). Their
     `params` are described in `app/validators/style_checks.py`.
     For `page_limit`, `params.main_ends_before` lists the headings where the main text ends (for example
     Limitations, Acknowledgments, References), so only the pages before them count.
3. Restart Paper Forge. The venue appears in the dropdown; if something is wrong it is listed as
   *(unavailable)* and `GET /api/venues` explains why.
4. On that start, `run.bat` / `run.sh` run `scripts/warmup.py`, which caches the new template's LaTeX packages
   for offline use. `runtime/warmup.ok` lists the venues already cached; delete it to cache every venue again.

A new *kind* of check is a function `def my_check(ctx, check) -> CheckResult` decorated with
`@register("my_check")` in `app/validators/`, plus its name in `CheckType` (`app/models/venue.py`) and a short
"how to fix" text in `HOW_TO_FIX` (`app/agents/assistant.py`), which the assistant uses.

---

## 10. Running the tests

The test suite (`tests/`, `pytest.ini`, `requirements-dev.txt`) is part of the developer copy only; a copy
shared for use leaves it out. In the developer copy:

```bash
# Windows (portable runtime)
runtime\python\python.exe -m pip install --no-cache-dir pytest==9.1.1 httpx==0.28.1
runtime\python\python.exe -m pytest

# macOS/Linux (local runtime)
runtime/venv/bin/python -m pip install -r requirements-dev.txt
runtime/venv/bin/python -m pytest
```

The suite uses a fake Tectonic so it runs offline in seconds. To also test the real compiler, put `tectonic`
on your PATH and set `PAPERFORGE_REAL_TECTONIC=1`.

---

## 11. Troubleshooting

**Startup (Windows)**
- *"curl.exe was not found" / "tar.exe was not found"*: update to Windows 10 1803+ or Windows 11.
- *A download fails*: check the internet connection or proxy, then run `run.bat` again. Partial steps are
  skipped once complete. `run.bat reset` starts from scratch.
- *"Installing Python packages failed"*: usually a network or antivirus problem. (Older copies failed with
  "Cannot import 'setuptools.build_meta'"; the launcher now installs only prebuilt packages, using
  `vendor\wheels` for bibtexparser, so update the folder if you see that.) Run `run.bat` again; if your
  antivirus quarantined files in `runtime\`, allow the folder and run `run.bat reset`.
- *The window closes immediately*: open Command Prompt in the folder and run `run.bat` to read the message.
- *Port already in use*: `set PAPERFORGE_PORT=8001 && run.bat`.

**Startup (Docker)**
- *"Docker is installed but not running"*: start Docker Desktop and wait for it to finish starting.
- *Build fails while downloading Tectonic or LaTeX packages*: the build needs internet; retry
  `docker compose build --no-cache`.
- *Linux: permission denied in `output`*: `sudo chown -R 1000 output`.

**Tectonic / LaTeX**
- *"Tectonic was not found"*: start with `run.bat`/`run.sh` (they install it) or set `PAPERFORGE_TECTONIC`.
- *"not in the cache" / "unable to fetch"*: a package not used by the sample paper is needed. Paper Forge retries
  with downloads allowed automatically; this needs internet once per new package.
- *Compilation failed*: open the report; *Failed checks* quotes the LaTeX error and line number. Fix the
  source (or open the LaTeX ZIP in Overleaf) and upload again. Common causes: custom `.sty` files you did not
  upload, commands from packages the venue forbids, or EPS figures.
- *Text in the margin warnings*: Paper Forge already tried `\sloppy` and shrinking wide tables; rephrase long
  URLs or words, or split wide tables.
- *Over the page limit*: shorten the paper; Paper Forge never deletes content to fit.

**AI modes**
- *Gemini "rate limit reached" / "daily quota used up"*: free-tier limits are per minute and per day. The job
  continues on rules (marked *partly agentic*). Lower "Most AI requests per paper", try later, or enable Ollama
  as a fallback.
- *"Agentic mode needs an AI provider"*: Full and Partial need a saved Gemini key (or Ollama). Choose Off, or
  add a key in Settings.
- *Gemini "rejected the API key"*: paste the key again; make sure the Generative Language API is enabled for it.
- *"Gemini unreachable"*: check the internet connection. On macOS with Python from python.org, run
  *Install Certificates.command* once (see section 3).
- *Gemini model "no longer offered"*: pick another model in Settings; the list shows the models your key can use.
- *Ollama "not reachable"*: start Ollama (`ollama serve`) and check the URL. In Docker mode use
  `http://host.docker.internal:11434`.
- *Ollama "model not installed"*: `ollama pull <model name>`.
- *The assistant says "The AI could not answer (...), so this is Paper Forge's built-in answer"*: the reason in
  brackets is the same message the jobs show (rate limit, daily quota, key rejected, unreachable). Wait a minute
  (rate limit), try tomorrow (daily quota), or check the key with *Test Gemini* in Settings.
- *A suggested text was "left out"*: the AI's rewrite changed a number or a citation, so it was not shown. The
  explanation above it still applies; make the change yourself.
- *No assistant panel on the job page*: it appears only when the job has finished and produced a report. A
  cancelled job, or one stopped before the report, has none.

**Where are the logs?** The console window shows server logs. Each job folder
`output/jobs/<job id>/logs/` has every compile result (`compile_N.json`) and, after an unexpected error,
`traceback.txt` (API keys are redacted).

---

## 12. Folder layout

```
paper-forge/
├── run.bat / run.sh          launchers (portable/local or Docker)
├── Dockerfile, docker-compose.yml
├── requirements.txt          runtime Python packages (pinned)
├── requirements-dev.txt      + test tools (developer copy only)
├── vendor/wheels/            prebuilt bibtexparser wheel (PyPI only ships it as source; avoids a build step)
├── app/                      FastAPI app: routes, agents (pipeline steps), parsers, formatters,
│                             compilers, validators, models, services (AI, storage), static UI
├── templates/<venue>/        each venue's official class/style files (unmodified) + Jinja2 templates
├── venue_rules/              one JSON file per venue
├── sample_paper/             LaTeX, Markdown and DOCX versions of a short sample paper
├── scripts/warmup.py         fills the LaTeX package cache
├── scripts/make_zip.py       makes the ZIP to share (run.bat zip)
├── tests/                    pytest suite (uses tests/fake_tectonic.py; developer copy only)
├── docs/PLAN.md, docs/schemas plan and JSON Schemas of the data contracts (developer copy only)
├── docs/VENUE_GUIDELINES.md  each venue's official author guidelines, with sources, behind its rules
├── docs/DESIGN.md            the web page's design tokens (light and dark)
├── runtime/                  created on first start: private Python/venv, Tectonic, caches (safe to delete)
└── output/                   your data: paperforge.db, settings.json, jobs/<id>/{uploads,work,final,logs}
                              (final/chat.json holds the assistant conversation once you use it)
```
