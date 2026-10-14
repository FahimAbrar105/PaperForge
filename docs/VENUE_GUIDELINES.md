# Venue formatting guidelines for rule-based checks

Researched 2026-10-13 from primary sources (official sites and GitHub kits). Each bullet ends with a source key, and each key is listed with its URL at the top of its section.
Markers: **[fix]** = safe to auto-correct. **[warn]** = report to the user only. "UNCONFIRMED" = could not verify in a primary source.

---

## 1. IEEE conference (IEEEtran, conference mode)

Sources:
- [T] IEEE conference template, conference_101719.tex (official, on Overleaf): https://www.overleaf.com/latex/templates/ieee-conference-template/grfzhhncsfqn
- [ESM] IEEE Editorial Style Manual for Authors: https://journals.ieeeauthorcenter.ieee.org/wp-content/uploads/sites/7/IEEE-Editorial-Style-Manual-for-Authors.pdf
- [RG] IEEE Reference Style Guide for Authors, V3.28.2025: https://journals.ieeeauthorcenter.ieee.org/wp-content/uploads/sites/7/IEEE_Reference_Guide.pdf
- [AC] IEEE Author Center, "Structure your article": https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-the-text-of-your-article/structure-your-article/
- [AI] IEEE conference submission policies (AI): https://conferences.ieeeauthorcenter.ieee.org/author-ethics/guidelines-and-policies/submission-policies/
### Abstract and keywords
- Abstract is one paragraph of 150–250 words, with no numbered equations, numbered citations or footnotes. [warn] [ESM]
- The journal guide says "single paragraph up to 250 words" and "without abbreviations". The conference template gives no word count. [AC] [T]
- No symbols, special characters, footnotes or math in the title or abstract. [warn] [T]
- Define acronyms in the abstract, then define them again at first use in the body. [warn] [ESM] [T]
- "Index Terms appear in alphabetical order." [fix: sort `IEEEkeywords`] [ESM]
- Use 3–5 keywords, taken from the IEEE Thesaurus. [warn] [AC]
### Title and headings
- Titles use title case: articles, coordinating conjunctions and short prepositions stay lowercase. [warn] [ESM] No subtitles, because Xplore does not capture them. [warn] [T]
- Avoid "new" and "novel" in the title. [warn] [AC]
- Do not use abbreviations in the title or headings unless unavoidable. [warn] [T]
- Section headings use Roman numerals and are centered. IEEEtran sets their style. [ESM] Do not number headings by hand. [warn] [T]
- A section with fewer than two subsections should have no subheads, so a lone "A." or "1)" is an error. [warn] [T]
### Figures, tables and cross-references
- Figure captions go below the figure. Table heads go above the table, so `\caption` comes before `tabular`. [fix: move] [T]
- Caption form is "Fig. 1. Text." A table caption takes no final period. [warn] [ESM] Tables are numbered with Roman numerals ("TABLE I", "Table I"). IEEEtran does this automatically. [ESM]
- Write "Fig. 1" everywhere, even at the start of a sentence. Never write "Figure 1". [fix] [T] [ESM] Write "Section II", with a capital S. [fix] [ESM]
- Refer to equations as "(1)", not "Eq. (1)" or "equation (1)". At the start of a sentence, write "Equation (1)". [fix] [T] [ESM]
- Figure labels use 8 pt. Axis labels use words, not symbols, with units in parentheses. [warn] [T] Place figures and tables at the top or bottom of a column. [warn] [T]
- Color-only figures: UNCONFIRMED. The template does not address it.
### Equations
- Number equations consecutively. [T] Punctuate equations with commas or periods when they are part of a sentence. [warn; auto-fix is risky] [T] [ESM]
- An equation that ends a sentence ends with a period. [ESM]
- Italicize Roman symbols for quantities, but not Greek symbols. [T] Use a long dash for the minus sign. [T]
- Use `align` or `IEEEeqnarray`, not `eqnarray`. [warn] [T]
- Upright operators such as `\min` and `\mathrm{Var}`: UNCONFIRMED in IEEE text. This is general math-typesetting practice.
### Citations and references
- Number citations consecutively within brackets. Sentence punctuation follows the bracket. [T] Write "as in [3]", not "Ref. [3]" or "reference [3]". At the start of a sentence, write "Reference [3] shows…". [fix] [T]
- Do not put the author's name with a citation number unless the name is integral to the sentence. [warn] [ESM]
- In text, use "et al." for 3 or more authors. [RG] In the reference list, use "et al." after the first author when there are more than six authors. [RG] The template says "Unless there are six authors or more give all authors' names". The two sources disagree on the threshold.
- Journal format: `J. K. Author, "Title," Abbrev. Journal, vol. x, no. x, pp. xxx–xxx, Abbrev. Month, year, doi: xxx.` The month is part of the format, for example "Sep.". Include the DOI when available. [warn] [RG]
- Conference format: `J. K. Author, "Title," in Abbrev. Name of Conf., City, State, Country, year, pp. xxx–xxx[, doi].` [warn] [RG] The month and day in printed proceedings are "(if provided)", so they are optional. A US location needs "USA" after the state. [RG]
- arXiv format: `J. K. Author, "Title," year, arXiv number.` [RG] Paper titles are in sentence case, inside double quotes. [T] [RG]
- Author names use initials, then surname. [RG]
- The guide states "Reference ranges in text will not include an en dash", but what it means is unclear. Do not auto-fix ranges. [RG]
### Other rules
- Use American spelling ("Change all British spellings to American spellings"). [warn] [ESM]
- Spell the heading "Acknowledgment": singular, with no "e" after "g". [fix] [T] [ESM]
- Footnote marks go after periods and commas, and before dashes, colons and semicolons. [fix] [ESM] Place footnotes at the bottom of the column. Do not put footnotes in the abstract or reference list. [T]
- Units: put a regular space between a number and its unit, use numerals with units, and prefer SI units. [warn] [ESM] [T] Put a zero before a decimal point ("0.25"). [fix] [T]
- "data" is plural. Write "et al.", with no period after "et". [warn] [T]
- Affiliations must include city and country. [warn] [AC] [T]
- AI-generated content must be disclosed in the Acknowledgment section, naming the system and the sections it was used in. Disclosure is recommended, but not required, for editing and grammar help. [warn] [AI]
- Remove all template guidance text before submission. [warn] [T] Page limit, review mode and paper size: set by each conference's call for papers. [T] Balanced columns on the last page: UNCONFIRMED in [T].

---

## 2. ACL / ARR (*ACL)

Sources:
- [AF] ACL Paper formatting guidelines (source of acl-org.github.io/ACLPUB/formatting.html): https://raw.githubusercontent.com/acl-org/ACLPUB/master/docs/formatting.md
- [AR] ACL review version (anonymity): https://raw.githubusercontent.com/acl-org/ACLPUB/master/docs/review-version.md
- [AK] acl_latex.tex in the official kit: https://github.com/acl-org/acl-style-files/blob/master/acl_latex.tex
- [ARR] ARR call for papers: https://aclrollingreview.org/cfp
### Abstract, keywords and title
- Abstract is at most 200 words, in plain text with no extra markup or LaTeX commands. [warn] [AF] No keywords section (n/a).
- Title is in title case (APA). Do not write it in all capitals, except acronyms such as "BLEU". [fix/warn] [AF] Title metadata is plain text with no LaTeX. [warn] [AF]
- Authors' full names. Surnames not in all caps. No footnotes for affiliations. Affiliations give a complete address. [warn] [AF]
### Headings and layout
- Sections are numbered with Arabic numerals. Heading case is not specified (UNCONFIRMED). [AF] Paper size is A4, in two columns. [AF] The review version has a ruler and page numbers. The final version has neither. [AF]
### Figures, tables and cross-references
- Captions go below figures **and tables**. [AF] The kit puts `\caption` after `tabular`, and after `\includegraphics` for figures. [AK]
- Caption form is "Figure 1: Caption." / "Table 1: Caption.", 10 pt. One-line captions are centered; longer ones are left-aligned. [AF]
- Text in figures and tables should match the body font size where possible. [warn] [AF] Figures must not rely solely on color. [warn] [AF]
- No rule on cross-reference wording. The kit spells out "Table~\ref", "Figure~\ref", "Section~\ref", "Equation~\ref" and "Appendix~\ref". That is a convention, not a rule. [AK]
- Equation rules: none in [AF]. The kit numbers its display equation. [AK] Footnotes: 9 pt, at the bottom of the page. No rule on placement relative to punctuation (UNCONFIRMED). [AF]
### Citations and references
- Author–year citations. "Refrain from using full citations as sentence constituents": write "Gusfield (1997) showed" (`\citet`), not "(Gusfield, 1997) showed" (`\citep` used as a noun). [warn] [AF] [AK]
- Use "et al." for more than two authors. Two authors are written "A and B". Collapse multiple citations into one pair of parentheses. [AF]
- The References heading is unnumbered and comes before the appendices. Order is alphabetical by first author. [AF] Use full author names, not initials. [warn] [AF]
- Include DOIs where possible, or ACL Anthology links; the kit says "DOIs or URLs when possible". [warn] [AF] [AK] Cite the refereed, archival version instead of arXiv when one exists. [warn] [AF]
### Required and optional sections
- A "Limitations" section is **required**. It goes after the conclusion and before the references, does not count toward pages, and adds no new results. A paper without one is desk-rejected. [AF] [ARR]
- Ethics / broader impact is optional and does not count toward pages. [AF] [ARR]
- Acknowledgments are unnumbered, go immediately before the references, do not count toward pages, and are **not allowed in the review version**. [AF] [AR]
- The Responsible NLP Checklist is required, through the submission form. [ARR] AI used for writing or coding is disclosed in the checklist, with details in the Acknowledgements. Grammar checkers are exempt. [ARR]
### Anonymity and page limits
- Review version: no names, affiliations or identifying URLs. [AR] [ARR] Self-citation in the third person: "Gusfield (1997) previously showed". Avoid "Anonymous" citations. [AR] [ARR] No download-tracking links such as Dropbox. Supplementary material is anonymized. [ARR]
- Long papers: 8 pages (9 final). Short papers: 4 pages (5 final). [AF]
- References, Limitations, Ethics, Acknowledgments and appendices are unlimited. Appendices go after the references, in two columns. [AF] [ARR]
- Spelling variety is not specified; the guide itself uses British "prioritise". [AF]

---

## 3. ICLR 2026 / 2027

Sources:
- [IT6] iclr2026_conference.tex: https://github.com/ICLR/Master-Template/blob/master/iclr2026/iclr2026_conference.tex
- [IT7] iclr2027_conference.tex: https://github.com/ICLR/Master-Template/blob/master/iclr2027/iclr2027_conference.tex
- [IG6] ICLR 2026 Author Guide: https://iclr.cc/Conferences/2026/AuthorGuide
- [IG7] ICLR 2027 Author Guidelines: https://www.iclr.cc/Conferences/2027/AuthorGuidelines
### Abstract, keywords, title and headings
- "The abstract must be limited to one paragraph." No word limit is stated (the OpenReview field limit is UNCONFIRMED). [warn] [IT6] [IT7] Abstracts must be genuine; placeholder abstracts are removed. [IG6]
- No keywords section in the paper (n/a). Title is 17 pt, small caps, left-aligned, set by the style file. Title capitalization rules: UNCONFIRMED. [IT6] Headings are small caps, flush left, set by the style file. Heading case is not specified (UNCONFIRMED). [IT6]
### Figures and tables
- Figure caption goes **after (below)** the figure. Table number and title go **before (above)** the table; the kit has `\caption` before `tabular`. [fix] [IT6]
- Figure captions and table titles are lowercase except the first word and proper nouns, so sentence case. [warn] [IT6] Figures should make sense printed in black and white. [warn] [IT6]
- Cross-reference wording: no rule. [IT6]
### Equations and footnotes
- Equation rules: none stated.
- Footnotes are numbered and go at the bottom of the page. Use the author `\thanks` footnote for author information, not funding. [IT6]
### Citations and references
- Author–year citations with natbib. Use `\citet` when the authors are part of the sentence and `\citep` otherwise. [warn] [IT6] Use "et al." for more than two authors. [IT6]
- References are listed alphabetically by author. Any style is allowed if used consistently. [IT6]
### Required and optional sections
- **2027:** "AI use statement" is **required**, at most 1 page, and not counted. [IT7] [IG7]
- **2026:** an LLM-usage section is required if LLM use was significant. It may go in the appendix and is not counted. [IG6]
- Ethics statement is recommended, at most 1 page, before the references, and not counted. [IT7] [IG6]
- Reproducibility statement is recommended, before the references, and not counted. [IT7] [IG6]
- Author Contributions is optional. Acknowledgments use an unnumbered third-level heading at the end. [IT6]
### Anonymity and page limits
- Double-blind. Self-citations in the third person. Do not refer explicitly to your own arXiv version. [IG6] [IG7] Links only if fully anonymous and the host does not track visitors. [IG6] [IG7]
- Acknowledgments in the review version: not explicitly addressed (UNCONFIRMED). Hiding them is the safe choice.
- Main text: at most 9 pages at submission and 10 pages for camera-ready. Over-length papers are desk-rejected. [IT6] [IG6] [IG7]
- References and appendices (after the bibliography) are unlimited. [IT6] [IG6] [IG7] US Letter paper. Pages numbered. [IT6]

---

## 4. CVPR 2026

Sources:
- [CK] Official author kit (cvpr-org/author-kit, "updated for CVPR 2026"), sec/1_intro.tex and sec/2_formatting.tex: https://github.com/cvpr-org/author-kit
- [CS] cvpr.sty in the kit: https://github.com/cvpr-org/author-kit/blob/main/cvpr.sty
- [CG] CVPR 2026 Author Guidelines: https://cvpr.thecvf.com/Conferences/2026/AuthorGuidelines
### Abstract and keywords
- Abstract: italic, fully justified, 10 pt. No word limit ("look at previous abstracts"). [CK] No keywords section (n/a).
### Title and headings
- Title is in title case: capitalize nouns, pronouns, verbs, adjectives and adverbs. Articles, coordinating conjunctions and prepositions stay lowercase unless they come first. [fix/warn] [CK]
- Headings are in **sentence case** ("Initially capitalize only the first word of section titles"). [fix/warn] [CK] Third-order headings are discouraged. [warn] [CK]
### Figures and tables
- Table captions go **above**; the kit has `\caption` before `tabular`. Figure captions go **below**. [fix] [CK]
- Captions are 9 pt with a period separator: "Figure 1. Text" (caption package `labelsep=period`). Short captions are centered. [CS] [CK]
- Fonts in figures should match the body text. [warn] [CK] Do not rely only on color; add a second visual cue. [warn] [CK]
### Cross-references and equations
- Use `\cref`, which renders "Fig. 1", "Tab. 1", "Sec. 1", "Eq. (1)". At the start of a sentence, `\Cref` renders "Figure 1", "Table 1", "Section 1", "Equation (1)". [fix] [CK] [CS] (compile-tested)
- Number all sections and **all displayed equations**. [warn] [CK]
### Footnotes, citations and references
- Use footnotes sparingly. They go at the bottom of the column, 8 pt. [CK]
- Numbered citations in square brackets. Several citations at once go in numerical order (natbib `sort&compress`). [CK] [CS]
- Use `\etal` ("et al.") only for 3 or more authors. Never write "et. al.". Use the `\eg`, `\ie`, `\vs` macros. [fix] [CK] [CS]
- The bibliography style is `ieeenat_fullname`, with full names. Include page numbers, and editors for books. [warn] [CK] Cite the peer-reviewed version of an arXiv paper when one exists. [warn] [CG]
### Required and optional sections
- No required statement sections. Discuss significant negative impacts. State IRB approval when human data is used. [CG] LLM use is allowed, and authors are responsible for the content. Hidden prompt-injection text leads to desk rejection. [CG]
### Anonymity
- Do not say "my" or "our" when citing previous work. Write "as Smith and Jones show in [7]". [warn] [CK]
- **No acknowledgments in the review version.** [CK] [CG]
- **No external links at all.** For code, write "will be made publicly available". [warn] [CG]
- The paper ID must appear in the review version. [CK] Supplementary material is anonymized. [CG]
### Page limits
- 8 pages, including figures and tables. References are unlimited. [CK] [CG] Extra page for camera-ready: UNCONFIRMED.

---

## 5. ACM sigconf (acmart)

Sources:
- [AS] acmart samples.dtx, the sample-sigconf source text: https://github.com/borisveytsman/acmart/blob/master/samples/samples.dtx
- [AD] acmart.dtx v2.21 (2026/10/04): https://github.com/borisveytsman/acmart/blob/master/acmart.dtx
- [TP] ACM "Preparing your article with LaTeX": https://authors.acm.org/proceedings/production-information/preparing-your-article-with-latex
- [AP] ACM Policy on Authorship (generative AI): https://www.acm.org/publications/policies/new-acm-policy-on-authorship
- [DF] ACM, "Describing figures": https://www.acm.org/publications/taps/describing-figures/
### Abstract, keywords and title
- Abstract is short, one or two paragraphs. No word limit. [warn] [TP]
- `\keywords{}` (comma-separated) and CCS concepts (`CCSXML` plus `\ccsdesc`, generated at dl.acm.org/ccs) are **required for papers of 3 pages or more**. [warn] [AS] [TP] Keyword order is not specified.
- Capitalize the title appropriately (capitalizemytitle.com). No `\\` line breaks in the title. Use `\title[short]{…}` for a long title. [fix/warn] [AS] [TP]
### Authors and headings
- One `\author` per person. Each author has `\institution`, `\city` and `\country`, and a separate `\email`. Full names. [warn] [AS] [TP]
- Heading case is not specified (UNCONFIRMED). Since acmart v2.08, sigconf no longer uppercases headings. [AD]
- Do not fake headings with bold text at the start of a paragraph. Do not remove numbering. [warn] [AS] [TP]
### Figures and tables
- Table captions go **above**. Figure captions go **below**. [fix] [AS]
- Use `\midrule` to separate table header rows. [warn] [AS]
- Every non-decorative figure needs `\Description{}`. It is plain text, under 2000 characters, and must not repeat the caption. [warn] [AS] [DF] The ACM author page asks for `\Description` on tables too. [TP]
- acmart warns "A possible image without description". [AD]
- Cross-reference wording: no rule.
### Equations
- Numbered (`equation`) and unnumbered (`displaymath`) display equations are both shown as valid. [AS]
### Citations and references
- Numbered citations by default. Author–year only for venues that require it (`\citestyle{acmauthoryear}`). [AS] Bibliography style `ACM-Reference-Format`. Full first names. Include title, year, volume, number, pages and DOI. Do not shorten reference fields. [warn] [AS] [TP]
- Footnotes: no rule.
### Required sections and template rules
- Acknowledgments must use `\begin{acks}`, not `\section`. The environment is suppressed automatically in `anonymous` mode. [fix] [AS] [AD]
- Rights commands (`\setcopyright`, `\acmConference`, `\acmDOI`…) and the ACM Reference Format are required in the final version, and are needed for papers longer than 1 page. [warn] [AS] [TP]
- Generative-AI use must be disclosed, preferably in the acknowledgments. Spelling and grammar tools are exempt. [warn] [AP]
- Template changes are not allowed: margins, fonts, `\vspace` tweaks, or packages not on the approved list. [warn] [AS] [TP] TAPS also says to refrain from `\newcommand`, which causes validation errors. [warn] [TP]
### Anonymity and page limits
- Use the `anonymous,review` options. No author information, no acknowledgments, and no citations or related-work text that reveals the authors. [warn] [AS] [TP]
- Page limit: set by each venue's call for papers. Spelling variety is not specified.

---

## Checkable summary

| Rule | IEEE | ACL | ICLR | CVPR | ACM |
|---|---|---|---|---|---|
| Abstract length | 150–250 words | ≤200 words | none stated | none stated | none stated |
| Abstract paragraphs | 1 | not stated | 1 | not stated | 1–2 |
| Abstract: no math/cites/footnotes | yes | plain text, no LaTeX | n/a | n/a | n/a |
| Keywords | Index Terms, 3–5 | n/a | n/a | n/a | required if ≥3 pages |
| Keyword order | alphabetical | n/a | n/a | n/a | not stated |
| CCS concepts | n/a | n/a | n/a | n/a | required if ≥3 pages |
| Title case | title case | title case (APA) | UNCONFIRMED | title case | capitalize appropriately |
| No math/symbols in title | yes | plain text | n/a | n/a | no `\\` |
| Heading case | title case (ESM) | UNCONFIRMED | UNCONFIRMED | sentence case | UNCONFIRMED |
| Lone subsection forbidden | yes | not stated | not stated | not stated | not stated |
| Figure caption | below | below | below | below | below |
| Table caption | above | **below** | above | above | above |
| Caption label | "Fig. 1." / "TABLE I" | "Figure 1:" | style default | "Figure 1." | style default |
| Caption case | sentence | not stated | sentence case | not stated | not stated |
| Figure ref, mid-sentence | Fig. 1 | Figure 1 (kit) | not stated | Fig. 1 | not stated |
| Figure ref, sentence start | Fig. 1 | Figure 1 (kit) | not stated | Figure 1 | not stated |
| Table ref | Table I | Table 1 (kit) | Table 1 (kit) | Tab. 1 / Table 1 | not stated |
| Section ref | Section II | Section 1 (kit) | not stated | Sec. 1 / Section 1 | not stated |
| Equation ref, mid-sentence | (1) | Equation 1 (kit) | not stated | Eq. (1) | not stated |
| Equation ref, sentence start | Equation (1) | Equation 1 (kit) | not stated | Equation (1) | not stated |
| Number all display equations | consecutive | not stated | not stated | required | optional |
| Equation punctuation | required | not stated | not stated | not stated | not stated |
| Citation style | numeric [n] | author–year | author–year | numeric [n] | numeric (default) |
| Citation as noun | "Reference [3]" at start | use \citet | use \citet | allowed | not stated |
| et al. in text | 3+ authors | >2 authors | >2 authors | 3+ (\etal) | not stated |
| et al. in reference list | >6 authors (RG) | full names | not stated | full names | full names |
| Reference order | citation order | alphabetical | alphabetical | numeric (sorted) | style default |
| Journal month in references | yes (Abbrev. Month) | not stated | not stated | not stated | not stated |
| Conference city/country in references | yes; month optional | as in examples | not stated | not stated | not stated |
| DOI in references | when available | required when possible | not stated | not stated | include |
| Prefer published over arXiv | not stated | yes | not stated | yes | not stated |
| Footnote vs punctuation | after . , ; before — : ; | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED |
| Spelling variety | American | not stated | not stated | not stated | not stated |
| Define abbreviations at first use | yes (also after abstract) | not stated | not stated | not stated | not stated |
| Number–unit spacing | regular space, SI | not stated | not stated | not stated | not stated |
| Color-only figures | UNCONFIRMED | forbidden | B/W-readable | forbidden | via \Description |
| Figure font size | 8 pt labels | match body | legible | match body | not stated |
| Figure alt text | not stated | not stated | not stated | not stated | \Description required |
| Limitations section | n/a | **required** | n/a | n/a | n/a |
| Ethics / impact section | n/a | optional | recommended ≤1 page | if negative impacts | n/a |
| Reproducibility statement | n/a | n/a | recommended | n/a | n/a |
| AI-use disclosure | Acknowledgment | checklist + Acks | 2027 required; 2026 if significant | not required | Acknowledgments |
| Acknowledgments in review | per CFP | removed | UNCONFIRMED | removed | auto-removed |
| Acknowledgments heading | "Acknowledgment" | unnumbered | unnumbered \subsubsection* | not stated | acks env |
| Self-citation | per CFP | third person | third person | third person, no "our" | no revealing cites |
| Links in review | per CFP | anonymous, no tracking | anonymous, no tracking | none allowed | not revealing |
| Main-text page limit | per CFP | 8 long / 4 short | 9 | 8 | per CFP |
| Camera-ready extra | per CFP | +1 | 10 total | UNCONFIRMED | per CFP |
| References counted | per CFP | no | no | no | per CFP |
| Appendix | per CFP | after refs, 2-column, unlimited | after refs, unlimited | supplementary | after refs |
| Paper size | per CFP | A4 | US Letter | US Letter | template |
| Paper ID in review | n/a | n/a | n/a | required | \acmSubmissionID |
