"""
ΚΗΜΔΗΣ Statistical Analysis v1.1 — uses kimdis_clean.db
Run:
  python analyze_kimdis.py          # all sections
  python analyze_kimdis.py --no-vat # skip interactive VAT lookup
"""

import argparse
import io
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB = "kimdis_clean.db"


def conn():
    return sqlite3.connect(DB)


# ── 1. Procedure type breakdown ──────────────────────────────────────────────

def section_procedure_types():
    c = conn().cursor()
    c.execute("""
        SELECT procedure_type, COUNT(*) as cnt, SUM(total_cost_without_vat) as total
        FROM awards
        GROUP BY procedure_type
        ORDER BY cnt DESC
    """)
    rows = c.fetchall()
    grand_cnt = sum(r[1] for r in rows)
    grand_amt = sum(r[2] for r in rows)

    print("\n" + "═"*70)
    print("  1. BREAKDOWN BY PROCEDURE TYPE (awards without VAT)")
    print("═"*70)
    print(f"  {'Procedure':<50} {'Count':>7}  {'%':>5}  {'Total (€)':>18}")
    print("  " + "─"*68)
    for r in rows:
        pct = r[1] / grand_cnt * 100
        print(f"  {(r[0] or 'N/A'):<50} {r[1]:>7,}  {pct:>4.1f}%  {r[2]:>18,.0f}")
    print("  " + "─"*68)
    print(f"  {'TOTAL':<50} {grand_cnt:>7,}  {'100%':>5}  {grand_amt:>18,.0f}")


# ── 2. Top 10 buyers & contractors per procedure type ───────────────────────

def _print_table(rows, vat_label, name_label, indent="  "):
    print(f"{indent}{'#':>3}  {vat_label:<14}  {'Awards':>6}  {'Total (€)':>16}  {name_label}")
    print(indent + "─"*82)
    for i, r in enumerate(rows, 1):
        name = (r[1] or "")[:45]
        print(f"{indent}{i:>3}.  {(r[0] or '?'):<14}  {r[2]:>6,}  {r[3]:>16,.0f}  {name}")


def section_top_per_type(limit=10):
    c = conn().cursor()
    c.execute("""
        SELECT procedure_type, COUNT(*) as cnt, SUM(total_cost_without_vat) as total
        FROM awards
        GROUP BY procedure_type
        ORDER BY cnt DESC
    """)
    types = c.fetchall()

    print("\n" + "═"*70)
    print(f"  2. TOP {limit} BUYERS & CONTRACTORS BY PROCEDURE TYPE")
    print("═"*70)

    for proc_type, type_cnt, type_total in types:
        label = proc_type or "N/A"
        print(f"\n  ┌─ {label}")
        print(f"  │  {type_cnt:,} awards  |  €{type_total:,.0f} total")

        for sort_label, order in [("by number of awards", "cnt DESC"), ("by total amount", "total DESC")]:
            # Buyers
            c.execute(f"""
                SELECT organization_vat, MAX(organization_name), COUNT(*) as cnt,
                       SUM(total_cost_without_vat) as total
                FROM awards
                WHERE procedure_type = ?
                GROUP BY organization_vat
                ORDER BY {order}
                LIMIT ?
            """, (proc_type, limit))
            rows = c.fetchall()
            if rows:
                print(f"\n  │  Top {limit} Buyers ({sort_label}):")
                _print_table(rows, "Buyer VAT", "Buyer", indent="  │  ")

            # Contractors — use contractor_amount if manually set, else divide by co-contractor count
            c.execute(f"""
                SELECT ac.contractor_vat, MAX(ac.contractor_name), COUNT(*) as cnt,
                       SUM(CASE WHEN ac.contractor_amount IS NOT NULL
                                THEN ac.contractor_amount
                                ELSE a.total_cost_without_vat * 1.0 / cc.n END) as total
                FROM awards a
                JOIN award_contractors ac ON a.adam = ac.adam
                JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                     ON a.adam = cc.adam
                WHERE a.procedure_type = ?
                GROUP BY ac.contractor_vat
                ORDER BY {order}
                LIMIT ?
            """, (proc_type, limit))
            rows = c.fetchall()
            if rows:
                print(f"\n  │  Top {limit} Contractors ({sort_label}, amount = share of award):")
                _print_table(rows, "Contractor VAT", "Contractor", indent="  │  ")


# ── 3. Interactive VAT lookup ────────────────────────────────────────────────

def section_vat_lookup(limit=50):
    print("\n" + "═"*70)
    print("  3. VAT LOOKUP")
    print("═"*70)

    COALESCE_AMOUNT = """CASE WHEN ac.contractor_amount IS NOT NULL
                              THEN ac.contractor_amount
                              ELSE a.total_cost_without_vat * 1.0 / cc.n END"""

    while True:
        try:
            entry = input("\n  Enter VAT (or VAT1-VAT2 for pair, 'exit' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not entry or entry.lower() == "exit":
            return

        c = conn().cursor()

        # ── Pair mode ────────────────────────────────────────────────────────
        if "-" in entry:
            parts = [p.strip() for p in entry.split("-", 1)]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                print("  Invalid format. Use VAT1-VAT2.")
                continue
            vat_a, vat_b = parts

            c.execute("""
                SELECT DISTINCT procedure_type FROM awards ORDER BY
                (SELECT COUNT(*) FROM awards a2 WHERE a2.procedure_type = awards.procedure_type) DESC
            """)
            proc_types = [r[0] for r in c.fetchall()]

            found = False
            for buyer_vat, contractor_vat in [(vat_a, vat_b), (vat_b, vat_a)]:
                c.execute("SELECT MAX(organization_name) FROM awards WHERE organization_vat = ?", (buyer_vat,))
                buyer_name = c.fetchone()[0]
                c.execute("SELECT MAX(contractor_name) FROM award_contractors WHERE contractor_vat = ?", (contractor_vat,))
                contractor_name = c.fetchone()[0]
                if not buyer_name and not contractor_name:
                    continue

                header_printed = False
                for proc_type in proc_types:
                    c.execute(f"""
                        SELECT a.adam, a.procedure_type, {COALESCE_AMOUNT} as amount,
                               a.title
                        FROM awards a
                        JOIN award_contractors ac ON a.adam = ac.adam
                        JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                             ON a.adam = cc.adam
                        WHERE a.organization_vat = ? AND ac.contractor_vat = ?
                          AND a.procedure_type = ?
                        ORDER BY amount DESC
                    """, (buyer_vat, contractor_vat, proc_type))
                    rows = c.fetchall()
                    if not rows:
                        continue
                    if not header_printed:
                        print(f"\n  ── BUYER: {buyer_name or buyer_vat}  →  CONTRACTOR: {contractor_name or contractor_vat}")
                        header_printed = True
                        found = True
                    total = sum(r[2] for r in rows)
                    print(f"\n  Procedure: {proc_type or 'N/A'}  ({len(rows)} awards, €{total:,.0f} total)")
                    print(f"  {'#':>3}  {'ADAM':<20}  {'Amount (€)':>14}  Subject")
                    print("  " + "─"*80)
                    for i, r in enumerate(rows, 1):
                        subj = (r[3] or "")[:50]
                        print(f"  {i:>3}.  {r[0]:<20}  {r[2]:>14,.0f}  {subj}")

            if not found:
                print(f"\n  No transactions found between {vat_a} and {vat_b}.")
            continue

        # ── Single VAT mode ──────────────────────────────────────────────────
        vat = entry

        c.execute("SELECT COUNT(*), MAX(organization_name) FROM awards WHERE organization_vat = ?", (vat,))
        org_count, org_name = c.fetchone()

        c.execute("SELECT COUNT(*), MAX(contractor_name) FROM award_contractors WHERE contractor_vat = ?", (vat,))
        con_count, con_name = c.fetchone()

        if org_count == 0 and con_count == 0:
            print(f"\n  VAT {vat}: not found in database.")
            continue

        c.execute("""
            SELECT DISTINCT procedure_type FROM awards ORDER BY
            (SELECT COUNT(*) FROM awards a2 WHERE a2.procedure_type = awards.procedure_type) DESC
        """)
        proc_types = [r[0] for r in c.fetchall()]

        if org_count > 0:
            print(f"\n  ── BUYER: {org_name or vat}  (VAT {vat})  —  {org_count:,} awards total")
            for proc_type in proc_types:
                c.execute(f"""
                    SELECT ac.contractor_vat, MAX(ac.contractor_name), COUNT(*) as cnt,
                           SUM({COALESCE_AMOUNT}) as total
                    FROM awards a
                    JOIN award_contractors ac ON a.adam = ac.adam
                    JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                         ON a.adam = cc.adam
                    WHERE a.organization_vat = ? AND a.procedure_type = ?
                    GROUP BY ac.contractor_vat
                    ORDER BY total DESC
                    LIMIT ?
                """, (vat, proc_type, limit))
                rows = c.fetchall()
                if not rows:
                    continue
                print(f"\n  Procedure: {proc_type or 'N/A'}")
                _print_table(rows, "Contractor VAT", "Contractor")

        if con_count > 0:
            print(f"\n  ── CONTRACTOR: {con_name or vat}  (VAT {vat})  —  {con_count:,} contract lines total")
            for proc_type in proc_types:
                c.execute(f"""
                    SELECT a.organization_vat, MAX(a.organization_name), COUNT(*) as cnt,
                           SUM({COALESCE_AMOUNT}) as total
                    FROM awards a
                    JOIN award_contractors ac ON a.adam = ac.adam
                    JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                         ON a.adam = cc.adam
                    WHERE ac.contractor_vat = ? AND a.procedure_type = ?
                    GROUP BY a.organization_vat
                    ORDER BY total DESC
                    LIMIT ?
                """, (vat, proc_type, limit))
                rows = c.fetchall()
                if not rows:
                    continue
                print(f"\n  Procedure: {proc_type or 'N/A'}")
                _print_table(rows, "Buyer VAT", "Buyer")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-vat", action="store_true", help="Skip interactive VAT lookup")
    args = p.parse_args()

    section_procedure_types()
    section_top_per_type()

    if not args.no_vat:
        section_vat_lookup()


if __name__ == "__main__":
    main()
