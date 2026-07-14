# KIMDIS Analytics

A set of Python tools to harvest, clean, and interactively analyze Greek public procurement data from the official KIMDIS (ΚΗΜΔΗΣ) open data API.

Built as a weekend project to explore what a single developer can do with a well-designed public data API and some AI assistance.

---

## What is KIMDIS?

**KIMDIS (ΚΗΜΔΗΣ — Κεντρικό Ηλεκτρονικό Μητρώο Δημοσίων Συμβάσεων)** is Greece's mandatory electronic public procurement registry. It reached full operation in 2025.

Unlike older transparency systems where structured fields were optional and often left blank, KIMDIS is a transactional system: you cannot register a contract without completing all required fields. The result is a remarkably clean dataset — across 119,790 clean award records in this project's snapshot, price fields have **0% NULL values**. Every record has a verified amount, a contractor VAT number, and a publishing organization.

The API is open, documented, requires no API key, and returns paginated JSON. It is a model of how public data infrastructure should work.

---

## What this project does

| Script | What it does |
|--------|-------------|
| `bulk_harvester_auctions.py` | Pulls all award decisions (`AWRD`) from the `/auction` endpoint |
| `bulk_harvester_notices.py` | Pulls all procurement notices (`PROC`) from the `/notice` endpoint |
| `create_clean_db.py` | Filters the raw harvest into a clean SQLite database |
| `analyze_kimdis.py` | Runs statistical analysis and an interactive VAT lookup |
| `lookup.py` | Look up a single award record by ADAM number |

---

## Quick Start

```bash
pip install -r requirements.txt

python bulk_harvester_auctions.py    # ~20–40 min, produces kimdis_bulk_analytics.db
python bulk_harvester_notices.py     # ~10–20 min, appends to kimdis_bulk_analytics.db
python create_clean_db.py            # produces kimdis_clean.db (~seconds)
python analyze_kimdis.py             # interactive analysis
```

No API key needed. No special access. All data is public by law.

---

## Installation

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

Dependencies: `requests`, `urllib3`. That's it.

---

## Step-by-step Usage

### 1. Harvest award data (κατακυρώσεις)

```bash
python bulk_harvester_auctions.py
```

Hits the `/auction` endpoint page by page (100 records/page) and writes everything into `kimdis_bulk_analytics.db`. Handles rate limiting automatically (HTTP 429 → 12-second pause). Stops when the API returns an empty page.

Optional flags:
```bash
python bulk_harvester_auctions.py --start-page 500   # resume from page 500
python bulk_harvester_auctions.py --pages 100         # collect only 100 pages
```

### 2. Harvest tender notices (διακηρύξεις)

```bash
python bulk_harvester_notices.py
```

Same structure, hits the `/notice` endpoint. Writes into the same `kimdis_bulk_analytics.db`.

### 3. Create the clean database

```bash
python create_clean_db.py
```

Reads `kimdis_bulk_analytics.db`, applies filters, and writes `kimdis_clean.db`.

**Filters applied:**
- Exclude cancelled records
- Exclude records with price ≤ 0
- Exclude records where total with VAT < total without VAT (internal inconsistency)
- Exclude records above €10,000,000 (extreme outliers that skew averages)

Typical result: ~85% of records pass all filters.

### 4. Run the analysis

```bash
python analyze_kimdis.py             # full run with interactive VAT lookup
python analyze_kimdis.py --no-vat   # sections 1 and 2 only, no prompt
```

### 5. Look up a specific ADAM record

```bash
python lookup.py 26AWRD018581138
```

Prints all fields for that award and its contractor list. Falls back to the raw database if the record was filtered out of the clean one.

---

## Analysis Sections

### Section 1 — Procedure Type Breakdown

Count and total value of all awards by procedure type. Gives an immediate overview of how procurement is distributed (direct assignments vs. open tenders vs. negotiated procedures).

### Section 2 — Top 10 Buyers and Contractors per Procedure Type

For each procedure type, shows:
- Top 10 buying organizations (by count and by total awarded value)
- Top 10 contractors (by count and by total awarded value)

### Section 3 — Interactive VAT Lookup

Enter a VAT number and the tool detects whether it is a buyer, a contractor, or both, then shows their top 50 counterparties per procedure type sorted by total value.

**Two modes:**

**Single VAT** — profile of one organization:
```
Enter VAT (or VAT1-VAT2 for pair, 'exit' to quit): 094079101
```
Shows all contractors this buyer awarded to (if buyer), and/or all buyers who awarded to this VAT (if contractor).

**Pair mode** — transactions between two specific organizations:
```
Enter VAT (or VAT1-VAT2 for pair, 'exit' to quit): 094079101-997997760
```
Shows every individual award between the two VATs, in both directions, grouped by procedure type with ADAM number, amount, and title.

Type `exit` or press Enter on an empty line to quit the loop.

---

## Database Schema

**`awards`** — one row per award decision (AWRD records)

| Column | Description |
|--------|-------------|
| `adam` | ADAM reference number (e.g. `26AWRD018311471`) |
| `title` | Procurement title |
| `procedure_type` | e.g. `Απευθείας ανάθεση`, `Ανοιχτή διαδικασία` |
| `contract_type` | e.g. `Υπηρεσίες`, `Προμήθειες` |
| `budget` | Estimated budget |
| `total_cost_with_vat` | Final awarded amount including VAT |
| `total_cost_without_vat` | Final awarded amount excluding VAT |
| `organization_vat` | VAT of the buying organization |
| `organization_name` | Name of the buying organization |
| `signed_date` | Contract signing date |
| `submission_date` | Submission date |
| `cancelled` | 0 = active, 1 = cancelled |
| `year` | Derived from signed_date or submission_date |
| `nuts_code` | NUTS geographic code |
| `nuts_city` | City |

**`award_contractors`** — one row per contractor per award (awards can have multiple contractors)

| Column | Description |
|--------|-------------|
| `adam` | Links to `awards.adam` |
| `contractor_vat` | Contractor VAT number |
| `contractor_name` | Contractor name |
| `contractor_amount` | Per-contractor override amount (see Data Notes below) |

**`historical_tenders`** — same schema as `awards`, populated from `/notice` endpoint (PROC records)

---

## Data Limitations and Disclaimers

### What is NOT in this database

This database contains only two record types:

| Type | What it is | In our DB |
|------|-----------|-----------|
| `PROC` | Procurement notices (tender announcements) | ✅ Yes |
| `AWRD` | Award decisions (κατακυρώσεις) | ✅ Yes |
| `SYMV` | Contracts (συμβάσεις) | ❌ No |
| SYMV modifications | Contract extensions and amendments | ❌ No |

**Amounts in this database are award-time values** — what was decided at the moment of the award. The actual contract that follows (SYMV) may have a different value, and subsequent modifications may increase or decrease that further. If you need final execution amounts, those are in the SYMV records which would require a separate harvester.

### Year coverage

Data coverage is **comprehensive for 2026** (~113,000 records). Coverage for 2025 is **partial** (~6,700 records), because KIMDIS compliance was being phased in throughout 2025 and many organizations were slow to upload early-2025 records. Records from before 2025 are essentially absent.

If you are looking for a specific 2025 award and cannot find it, the most likely reason is that it was uploaded after this harvest was taken, or the organization had not yet complied at that time.

### Framework agreements and per-contractor amounts

In KIMDIS, **framework agreements** record the full ceiling value of the framework against every participating contractor. If a €9.7M framework has 10 contractors, the API returns 10 records each showing €9.7M — giving the appearance that each contractor received €9.7M when in reality the total is €9.7M shared among all.

The `contractor_amount` column in `award_contractors` exists to override this: where the real per-contractor execution amount is known (sourced manually from SYMV records on the KIMDIS website), it is stored here. The analysis uses `COALESCE(contractor_amount, total_cost / num_contractors)` to avoid double-counting.

As of this snapshot, `contractor_amount` overrides are present for a small number of known framework awards. The vast majority of records use the standard `total_cost_without_vat`.

### VAT number quality

VAT numbers in the source data are generally reliable but not perfect. One confirmed typo was found during development: contractor VAT `96763330` in record `26AWRD018398456` should be `996763330` (ΚΤΕΛ ΕΒΡΟΥ — missing leading digit). The fix is applied in the clean database. Other similar typos may exist in the raw data.

### Amount filter

Records above €10,000,000 are excluded from the clean database. This removes a small number of very large framework agreements whose ceiling values are not meaningful for statistical analysis of typical procurement. One manual amount correction is applied in `create_clean_db.py` for record `26AWRD018937371`, where the API value was approximately 1000× the correct amount (confirmed against the published PDF).

### All amounts are pre-VAT

`total_cost_without_vat` is the primary amount used throughout the analysis. Greek standard VAT is 24%.

---

## Technical Notes

- **Database**: SQLite. No server required.
- **Raw database**: `kimdis_bulk_analytics.db` — everything the API returned, unfiltered.
- **Clean database**: `kimdis_clean.db` — filtered, indexed, ready for analysis.
- **Re-running the harvest**: both harvesters use `ON CONFLICT(adam) DO NOTHING`, so re-running is safe and idempotent. You can also resume from a specific page with `--start-page`.
- **SSL**: The KIMDIS API endpoint uses a certificate that Python's default SSL verification rejects. Both harvesters disable SSL verification (`verify=False`) and suppress the resulting warning. This is intentional and safe for a read-only public API.
- **Rate limiting**: The API occasionally returns HTTP 429. The harvesters pause 12 seconds and retry automatically.

---

## Data Source

All data sourced from the official KIMDIS open data API:
`https://cerpp.eprocurement.gov.gr/khmdhs-opendata`

Endpoints used:
- `POST /auction` — award decisions
- `POST /notice` — procurement notices

No scraping. No proprietary data. No terms of service violations. The data is public by law under Greek Law 4412/2016 and EU Directive 2014/24/EU.

---

## License

MIT — use freely, attribution appreciated.
