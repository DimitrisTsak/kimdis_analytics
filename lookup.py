import argparse
import io
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def lookup(adam):
    conn = sqlite3.connect("kimdis_clean.db")
    c = conn.cursor()

    c.execute("SELECT * FROM awards WHERE adam = ?", (adam,))
    row = c.fetchone()
    cols = [d[0] for d in c.description]
    conn.close()

    if row:
        print("=== AWARD RECORD ===")
        for col, val in zip(cols, row):
            print(f"  {col:<30} {val}")

        conn2 = sqlite3.connect("kimdis_clean.db")
        c2 = conn2.cursor()
        c2.execute("SELECT contractor_vat, contractor_name FROM award_contractors WHERE adam = ?", (adam,))
        contractors = c2.fetchall()
        conn2.close()
        print("\n=== CONTRACTORS ===")
        for ct in contractors:
            print(f"  VAT: {ct[0]}  Name: {ct[1]}")
        return

    # Fall back to raw DB
    try:
        conn3 = sqlite3.connect("kimdis_bulk_analytics.db")
        c3 = conn3.cursor()
        c3.execute("SELECT * FROM awards WHERE adam = ?", (adam,))
        row2 = c3.fetchone()
        conn3.close()
        if row2:
            cols2 = [d[0] for d in c3.description]
            print("=== FOUND IN RAW DB (filtered out of clean DB) ===")
            for col, val in zip(cols2, row2):
                print(f"  {col:<30} {val}")
        else:
            print(f"Not found: {adam}")
    except Exception:
        print(f"Not found in clean DB: {adam}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Look up a KIMDIS award by ADAM number")
    parser.add_argument("adam", metavar="ADAM", help="ADAM reference number, e.g. 26AWRD018581138")
    args = parser.parse_args()
    lookup(args.adam)
