"""
Creates the empty schema in kimdis_bulk_analytics.db before harvesting.
Run once before the first harvest (GitHub Actions runs this automatically).
"""
import sqlite3

DB = "kimdis_bulk_analytics.db"

conn = sqlite3.connect(DB)
c = conn.cursor()

c.executescript("""
    CREATE TABLE IF NOT EXISTS awards (
        adam                    TEXT PRIMARY KEY,
        title                   TEXT,
        procedure_type          TEXT,
        contract_type           TEXT,
        budget                  REAL,
        total_cost_with_vat     REAL,
        total_cost_without_vat  REAL,
        organization_vat        TEXT,
        signed_date             TEXT,
        submission_date         TEXT,
        cancelled               TEXT,
        year                    INTEGER,
        nuts_code               TEXT,
        nuts_city               TEXT,
        organization_name       TEXT
    );

    CREATE TABLE IF NOT EXISTS historical_tenders (
        adam                    TEXT PRIMARY KEY,
        title                   TEXT,
        procedure_type          TEXT,
        contract_type           TEXT,
        budget                  REAL,
        total_cost_with_vat     REAL,
        total_cost_without_vat  REAL,
        organization_vat        TEXT,
        signed_date             TEXT,
        submission_date         TEXT,
        cancelled               TEXT,
        year                    INTEGER,
        nuts_code               TEXT,
        nuts_city               TEXT,
        organization_name       TEXT
    );

    CREATE TABLE IF NOT EXISTS award_contractors (
        adam             TEXT,
        contractor_vat   TEXT,
        contractor_name  TEXT,
        UNIQUE(adam, contractor_vat)
    );
""")

conn.commit()
conn.close()
print("Database schema ready.")
