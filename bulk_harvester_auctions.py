import sqlite3
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://cerpp.eprocurement.gov.gr/khmdhs-opendata/auction"
DB_NAME = "kimdis_bulk_analytics.db"


def extract_year(date_str):
    if date_str:
        try:
            return int(str(date_str)[:4])
        except (ValueError, IndexError):
            pass
    return None


def harvest_auctions(start_page=0, pages_to_collect=50):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    current_page = start_page
    total_awards = 0
    total_contractors = 0

    print(f"Harvesting /auction starting at page {start_page} ({pages_to_collect} pages)...")

    while current_page < (start_page + pages_to_collect):
        target_url = f"{BASE_URL}?page={current_page}&size=100"

        try:
            response = requests.post(target_url, headers=headers, json={}, verify=False)

            if response.status_code == 429:
                print("  Rate limit hit. Pausing 12 seconds...")
                time.sleep(12)
                continue

            if response.status_code != 200:
                print(f"  HTTP {response.status_code} on page {current_page}. Stopping.")
                break

            data = response.json()
            records = data.get("content", [])

            if not records:
                print("  Empty page — full depth reached.")
                break

            awards_batch = []
            contractors_batch = []

            for t in records:
                adam = t.get("referenceNumber")
                title = t.get("title")
                proc_type = (t.get("procedureType") or {}).get("value")
                contract_type = (t.get("contractType") or {}).get("value")
                budget = t.get("budget")
                total_with_vat = t.get("totalCostWithVAT")
                total_without_vat = t.get("totalCostWithoutVAT")
                org_vat = t.get("organizationVatNumber")
                signed_date = t.get("signedDate")
                sub_date = t.get("submissionDate")
                is_cancelled = 1 if t.get("cancelled") is True else 0
                nuts_code = (t.get("nutsCode") or {}).get("value")
                nuts_city = t.get("nutsCity")
                org_name = (t.get("organization") or {}).get("value")

                year = extract_year(signed_date) or extract_year(sub_date)

                awards_batch.append((
                    adam, title, proc_type, contract_type, budget,
                    total_with_vat, total_without_vat, org_vat,
                    signed_date, sub_date, is_cancelled, year,
                    nuts_code, nuts_city, org_name
                ))

                # Store every contractor linked to this award
                members = (t.get("contractingDataDetails") or {}).get("contractingMembersDataList") or []
                for m in members:
                    vat = m.get("vatNumber")
                    name = m.get("name")
                    if vat and adam:
                        contractors_batch.append((adam, vat, name))

            cursor.executemany("""
                INSERT INTO awards (
                    adam, title, procedure_type, contract_type, budget,
                    total_cost_with_vat, total_cost_without_vat, organization_vat,
                    signed_date, submission_date, cancelled, year,
                    nuts_code, nuts_city, organization_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(adam) DO NOTHING
            """, awards_batch)

            cursor.executemany("""
                INSERT INTO award_contractors (adam, contractor_vat, contractor_name)
                VALUES (?, ?, ?)
                ON CONFLICT(adam, contractor_vat) DO NOTHING
            """, contractors_batch)

            conn.commit()
            total_awards += len(awards_batch)
            total_contractors += len(contractors_batch)
            print(f"  Page {current_page}: {len(awards_batch)} awards, {len(contractors_batch)} contractor links.")

            time.sleep(0.3)
            current_page += 1

        except Exception as e:
            print(f"  Error on page {current_page}: {e}")
            break

    conn.close()
    print(f"\nAuction harvest complete. Awards: {total_awards} | Contractor links: {total_contractors}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Harvest /auction records into the analytics DB")
    parser.add_argument("--start-page", type=int, default=0, metavar="N",
                        help="Page to start from (default: 0)")
    parser.add_argument("--pages", type=int, default=9999, metavar="N",
                        help="Max pages to collect — stops early if API returns empty page (default: 9999 = all)")
    args = parser.parse_args()
    harvest_auctions(start_page=args.start_page, pages_to_collect=args.pages)
