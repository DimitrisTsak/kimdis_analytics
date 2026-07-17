"""
Creates kimdis_clean.db from kimdis_bulk_analytics.db applying these filters:

AWARDS (κατακυρώσεις):
  - cancelled = '0'                         (exclude cancelled)
  - total_cost_without_vat > 0              (positive price)
  - total_cost_with_vat > 0                 (positive price)
  - total_cost_with_vat >= total_cost_without_vat  (VAT logic consistent)
  - total_cost_without_vat <= 10,000,000    (exclude absurd outliers)
  - budget > 0 (when present)               (for budget field integrity)

NOTICES (διακηρύξεις):
  - cancelled = '0'
  - total_cost_without_vat > 0
  - total_cost_without_vat <= 10,000,000
"""

import sqlite3
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SRC = "kimdis_bulk_analytics.db"
DST = "kimdis_clean.db"
MAX_AMOUNT = 10_000_000


def create_clean_db():
    src = sqlite3.connect(SRC)
    dst = sqlite3.connect(DST)

    src.row_factory = sqlite3.Row
    sc = src.cursor()
    dc = dst.cursor()

    # ── Create tables ────────────────────────────────────────────────────────
    for table in ["awards", "historical_tenders"]:
        sc.execute(f"PRAGMA table_info({table})")
        cols = sc.fetchall()
        col_defs = ", ".join(f"{c['name']} {c['type']}" for c in cols)
        dc.execute(f"DROP TABLE IF EXISTS {table}")
        dc.execute(f"CREATE TABLE {table} ({col_defs})")

    # ── Awards ───────────────────────────────────────────────────────────────
    sc.execute("SELECT COUNT(*) FROM awards")
    total_awards = sc.fetchone()[0]

    sc.execute("""
        SELECT * FROM awards
        WHERE cancelled = '0'
          AND total_cost_without_vat > 0
          AND total_cost_with_vat > 0
          AND total_cost_with_vat >= total_cost_without_vat
          AND total_cost_without_vat <= ?
    """, (MAX_AMOUNT,))
    rows = sc.fetchall()

    dc.executemany(
        f"INSERT INTO awards VALUES ({','.join(['?']*len(rows[0]))})",
        [tuple(r) for r in rows]
    )

    clean_awards = len(rows)
    removed_awards = total_awards - clean_awards

    # ── Notices ──────────────────────────────────────────────────────────────
    sc.execute("SELECT COUNT(*) FROM historical_tenders")
    total_notices = sc.fetchone()[0]

    sc.execute("""
        SELECT * FROM historical_tenders
        WHERE cancelled = '0'
          AND total_cost_without_vat > 0
          AND total_cost_with_vat > 0
          AND total_cost_with_vat >= total_cost_without_vat
          AND total_cost_without_vat <= ?
    """, (MAX_AMOUNT,))
    rows = sc.fetchall()

    dc.executemany(
        f"INSERT INTO historical_tenders VALUES ({','.join(['?']*len(rows[0]))})",
        [tuple(r) for r in rows]
    )

    clean_notices = len(rows)
    removed_notices = total_notices - clean_notices

    # ── Award contractors (only for clean awards) ────────────────────────────
    sc.execute("SELECT COUNT(*) FROM award_contractors")
    total_contractors = sc.fetchone()[0]

    dc.execute("DROP TABLE IF EXISTS award_contractors")
    dc.execute("""
        CREATE TABLE award_contractors (
            adam              TEXT,
            contractor_vat    TEXT,
            contractor_name   TEXT,
            contractor_amount REAL
        )
    """)
    sc.execute("""
        SELECT ac.adam, ac.contractor_vat, ac.contractor_name
        FROM award_contractors ac
        INNER JOIN awards a ON a.adam = ac.adam
        WHERE a.cancelled = '0'
          AND a.total_cost_without_vat > 0
          AND a.total_cost_with_vat > 0
          AND a.total_cost_with_vat >= a.total_cost_without_vat
          AND a.total_cost_without_vat <= ?
    """, (MAX_AMOUNT,))
    rows = sc.fetchall()
    dc.executemany("INSERT INTO award_contractors (adam, contractor_vat, contractor_name) VALUES (?,?,?)", rows)
    clean_contractors = len(rows)

    # ── Manual corrections ────────────────────────────────────────────────────

    # API record had values ~1000x too large; PDF confirms €5,000 with VAT
    dc.execute("""
        UPDATE awards
        SET total_cost_without_vat = 4424.0,
            total_cost_with_vat    = 5482.72
        WHERE adam = '26AWRD018937371'
    """)

    # VAT typo in source data: ΚΤΕΛ ΕΒΡΟΥ recorded as 96763330 (missing leading 9)
    dc.execute("""
        UPDATE award_contractors
        SET contractor_vat = '996763330'
        WHERE contractor_vat = '96763330' AND adam = '26AWRD018398456'
    """)

    # Per-contractor real amounts for two taxi framework agreements
    # (26AWRD018311471 and 26AWRD018398456 — full ceiling recorded per contractor;
    #  real SYMV amounts sourced manually from KIMDIS website)
    contractor_amounts = [
        ('26AWRD018311471', '042271404',  81748.50),
        ('26AWRD018311471', '044925288',  23445.58),
        ('26AWRD018311471', '053737841',  24377.20),
        ('26AWRD018311471', '046297889',      0.00),
        ('26AWRD018311471', '061253582',  30240.42),
        ('26AWRD018311471', '075491560',  13775.74),
        ('26AWRD018311471', '125629971',  25002.87),
        ('26AWRD018311471', '801453375', 110028.63),
        ('26AWRD018311471', '996763330',      0.00),
        ('26AWRD018311471', '998136667', 200063.01),
        ('26AWRD018398456', '042271404',  81748.50),
        ('26AWRD018398456', '044925288',  23445.58),
        ('26AWRD018398456', '053737841',  24377.20),
        ('26AWRD018398456', '046297889',      0.00),
        ('26AWRD018398456', '061253582',  30240.42),
        ('26AWRD018398456', '075491560',  13775.74),
        ('26AWRD018398456', '125629971',  25002.87),
        ('26AWRD018398456', '801453375', 110028.63),
        ('26AWRD018398456', '996763330',      0.00),
        ('26AWRD018398456', '998136667', 200063.01),
    ]
    dc.executemany("""
        UPDATE award_contractors
        SET contractor_amount = ?
        WHERE adam = ? AND contractor_vat = ?
    """, [(amt, adam, vat) for adam, vat, amt in contractor_amounts])

    # ── Indexes ──────────────────────────────────────────────────────────────
    dc.execute("CREATE INDEX IF NOT EXISTS idx_awards_vat   ON awards(organization_vat)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_awards_proc  ON awards(procedure_type)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_awards_cost  ON awards(total_cost_without_vat)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_awards_year  ON awards(year)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_awards_adam  ON awards(adam)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_notices_vat  ON historical_tenders(organization_vat)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_notices_cost ON historical_tenders(total_cost_without_vat)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_ac_adam      ON award_contractors(adam)")
    dc.execute("CREATE INDEX IF NOT EXISTS idx_ac_vat       ON award_contractors(contractor_vat)")

    dst.commit()
    src.close()
    dst.close()

    # ── Report ───────────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  Clean DB created: {DST}")
    print(f"  Filter: cancelled=No, price>0, price<={MAX_AMOUNT:,}")
    print(f"{'='*55}")
    print(f"\n  {'Table':<24} {'Original':>10} {'Kept':>10} {'Removed':>10}")
    print(f"  {'-'*56}")
    print(f"  {'awards':<24} {total_awards:>10,} {clean_awards:>10,} {removed_awards:>10,}")
    print(f"  {'historical_tenders':<24} {total_notices:>10,} {clean_notices:>10,} {removed_notices:>10,}")
    print(f"  {'award_contractors':<24} {total_contractors:>10,} {clean_contractors:>10,} {total_contractors-clean_contractors:>10,}")
    print(f"  {'-'*56}")
    total_in  = total_awards + total_notices
    total_out = clean_awards + clean_notices
    print(f"  {'TOTAL (awards+notices)':<24} {total_in:>10,} {total_out:>10,} {total_in-total_out:>10,}")
    pct = total_out / total_in * 100
    print(f"\n  Kept: {pct:.1f}% of all records")


if __name__ == "__main__":
    create_clean_db()
