// ── Configuration ─────────────────────────────────────────────────────────────
// Local testing: copy kimdis_clean.db here, then:  python -m http.server 8080
// Production:    set this to your Cloudflare R2 public URL
const DB_URL = 'kimdis_clean.db';

// ── Terminal output ────────────────────────────────────────────────────────────
const output = document.getElementById('output');

function print(text = '') {
    output.appendChild(document.createTextNode(text + '\n'));
    output.scrollTop = output.scrollHeight;
}

// Returns a node whose text can be updated in place (used for progress bar)
function printMutable(text = '') {
    const span = document.createElement('span');
    span.textContent = text + '\n';
    output.appendChild(span);
    output.scrollTop = output.scrollHeight;
    return span;
}

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// ── Formatting helpers ─────────────────────────────────────────────────────────
function fmtN(n) {
    return Math.round(n || 0).toLocaleString('en-US');
}

// ── SQL helper ─────────────────────────────────────────────────────────────────
function query(db, sql, params = []) {
    const stmt = db.prepare(sql);
    if (params.length) stmt.bind(params);
    const rows = [];
    while (stmt.step()) rows.push(stmt.get());
    stmt.free();
    return rows;
}

// ── Table printer (mirrors Python _print_table exactly) ───────────────────────
function printTable(rows, vatLabel, nameLabel, indent = '  ') {
    print(
        indent +
        '#'.padStart(3) + '  ' +
        vatLabel.padEnd(14) + '  ' +
        'Awards'.padStart(6) + '  ' +
        'Total (€)'.padStart(16) + '  ' +
        nameLabel
    );
    print(indent + '─'.repeat(82));
    rows.forEach((r, i) => {
        print(
            indent +
            String(i + 1).padStart(3) + '.  ' +
            (r[0] || '?').padEnd(14) + '  ' +
            fmtN(r[2]).padStart(6) + '  ' +
            fmtN(r[3]).padStart(16) + '  ' +
            (r[1] || '').substring(0, 45)
        );
    });
}

// ── Section 1: Procedure type breakdown ───────────────────────────────────────
function section1(db) {
    const rows = query(db, `
        SELECT procedure_type, COUNT(*) as cnt, SUM(total_cost_without_vat) as total
        FROM awards
        GROUP BY procedure_type
        ORDER BY cnt DESC
    `);

    const grandCnt = rows.reduce((s, r) => s + r[1], 0);
    const grandAmt = rows.reduce((s, r) => s + r[2], 0);

    print('');
    print('═'.repeat(70));
    print('  1. BREAKDOWN BY PROCEDURE TYPE (awards without VAT)');
    print('═'.repeat(70));
    print(
        '  ' +
        'Procedure'.padEnd(50) + ' ' +
        'Count'.padStart(7) + '  ' +
        '%'.padStart(5) + '  ' +
        'Total (€)'.padStart(18)
    );
    print('  ' + '─'.repeat(68));

    for (const r of rows) {
        const pct = (r[1] / grandCnt * 100).toFixed(1) + '%';
        print(
            '  ' +
            (r[0] || 'N/A').padEnd(50) + ' ' +
            fmtN(r[1]).padStart(7) + '  ' +
            pct.padStart(5) + '  ' +
            fmtN(r[2]).padStart(18)
        );
    }

    print('  ' + '─'.repeat(68));
    print(
        '  ' +
        'TOTAL'.padEnd(50) + ' ' +
        fmtN(grandCnt).padStart(7) + '  ' +
        '100%'.padStart(5) + '  ' +
        fmtN(grandAmt).padStart(18)
    );
}

// ── Section 2: Top buyers & contractors per procedure type ────────────────────
async function section2(db, amountExpr, limit = 10) {
    const types = query(db, `
        SELECT procedure_type, COUNT(*) as cnt, SUM(total_cost_without_vat) as total
        FROM awards
        GROUP BY procedure_type
        ORDER BY cnt DESC
    `);

    print('');
    print('═'.repeat(70));
    print(`  2. TOP ${limit} BUYERS & CONTRACTORS BY PROCEDURE TYPE`);
    print('═'.repeat(70));

    for (const [procType, typeCnt, typeTotal] of types) {
        await sleep(0); // yield to browser between procedure types

        print('');
        print(`  ┌─ ${procType || 'N/A'}`);
        print(`  │  ${fmtN(typeCnt)} awards  |  €${fmtN(typeTotal)} total`);

        for (const [sortLabel, orderBy] of [
            ['by number of awards', 'cnt DESC'],
            ['by total amount',     'total DESC']
        ]) {
            // Buyers
            const buyers = query(db, `
                SELECT organization_vat, MAX(organization_name), COUNT(*) as cnt,
                       SUM(total_cost_without_vat) as total
                FROM awards
                WHERE procedure_type = ?
                GROUP BY organization_vat
                ORDER BY ${orderBy}
                LIMIT ${limit}
            `, [procType]);

            if (buyers.length) {
                print('');
                print(`  │  Top ${limit} Buyers (${sortLabel}):`);
                printTable(buyers, 'Buyer VAT', 'Buyer', '  │  ');
            }

            // Contractors — use per-contractor amount override where available
            const contractors = query(db, `
                SELECT ac.contractor_vat, MAX(ac.contractor_name), COUNT(*) as cnt,
                       SUM(${amountExpr}) as total
                FROM awards a
                JOIN award_contractors ac ON a.adam = ac.adam
                JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                     ON a.adam = cc.adam
                WHERE a.procedure_type = ?
                GROUP BY ac.contractor_vat
                ORDER BY ${orderBy}
                LIMIT ${limit}
            `, [procType]);

            if (contractors.length) {
                print('');
                print(`  │  Top ${limit} Contractors (${sortLabel}, amount = share of award):`);
                printTable(contractors, 'Contractor VAT', 'Contractor', '  │  ');
            }
        }
    }
}

// ── Section 3 — single VAT lookup ─────────────────────────────────────────────
function lookupSingle(db, vat, amountExpr) {
    const [[orgCount, orgName]] = query(db,
        'SELECT COUNT(*), MAX(organization_name) FROM awards WHERE organization_vat = ?', [vat]);
    const [[conCount, conName]] = query(db,
        'SELECT COUNT(*), MAX(contractor_name) FROM award_contractors WHERE contractor_vat = ?', [vat]);

    if (!orgCount && !conCount) {
        print(`\n  VAT ${vat}: not found in database.`);
        return;
    }

    const procTypes = query(db, `
        SELECT DISTINCT procedure_type FROM awards
        ORDER BY (SELECT COUNT(*) FROM awards a2 WHERE a2.procedure_type = awards.procedure_type) DESC
    `).map(r => r[0]);

    if (orgCount) {
        print(`\n  ── BUYER: ${orgName || vat}  (VAT ${vat})  —  ${fmtN(orgCount)} awards total`);
        for (const pt of procTypes) {
            const rows = query(db, `
                SELECT ac.contractor_vat, MAX(ac.contractor_name), COUNT(*) as cnt,
                       SUM(${amountExpr}) as total
                FROM awards a
                JOIN award_contractors ac ON a.adam = ac.adam
                JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                     ON a.adam = cc.adam
                WHERE a.organization_vat = ? AND a.procedure_type = ?
                GROUP BY ac.contractor_vat
                ORDER BY total DESC
                LIMIT 50
            `, [vat, pt]);
            if (!rows.length) continue;
            print(`\n  Procedure: ${pt || 'N/A'}`);
            printTable(rows, 'Contractor VAT', 'Contractor');
        }
    }

    if (conCount) {
        print(`\n  ── CONTRACTOR: ${conName || vat}  (VAT ${vat})  —  ${fmtN(conCount)} contract lines total`);
        for (const pt of procTypes) {
            const rows = query(db, `
                SELECT a.organization_vat, MAX(a.organization_name), COUNT(*) as cnt,
                       SUM(${amountExpr}) as total
                FROM awards a
                JOIN award_contractors ac ON a.adam = ac.adam
                JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                     ON a.adam = cc.adam
                WHERE ac.contractor_vat = ? AND a.procedure_type = ?
                GROUP BY a.organization_vat
                ORDER BY total DESC
                LIMIT 50
            `, [vat, pt]);
            if (!rows.length) continue;
            print(`\n  Procedure: ${pt || 'N/A'}`);
            printTable(rows, 'Buyer VAT', 'Buyer');
        }
    }
}

// ── Section 3 — pair VAT lookup ───────────────────────────────────────────────
function lookupPair(db, vatA, vatB, amountExpr) {
    const procTypes = query(db, `
        SELECT DISTINCT procedure_type FROM awards
        ORDER BY (SELECT COUNT(*) FROM awards a2 WHERE a2.procedure_type = awards.procedure_type) DESC
    `).map(r => r[0]);

    let found = false;

    for (const [buyerVat, contractorVat] of [[vatA, vatB], [vatB, vatA]]) {
        const buyerName   = (query(db, 'SELECT MAX(organization_name) FROM awards WHERE organization_vat = ?', [buyerVat])[0] || [])[0];
        const contractorName = (query(db, 'SELECT MAX(contractor_name) FROM award_contractors WHERE contractor_vat = ?', [contractorVat])[0] || [])[0];
        if (!buyerName && !contractorName) continue;

        let headerPrinted = false;

        for (const pt of procTypes) {
            const rows = query(db, `
                SELECT a.adam, a.procedure_type, ${amountExpr} as amount, a.title
                FROM awards a
                JOIN award_contractors ac ON a.adam = ac.adam
                JOIN (SELECT adam, COUNT(*) as n FROM award_contractors GROUP BY adam) cc
                     ON a.adam = cc.adam
                WHERE a.organization_vat = ? AND ac.contractor_vat = ? AND a.procedure_type = ?
                ORDER BY amount DESC
            `, [buyerVat, contractorVat, pt]);

            if (!rows.length) continue;

            if (!headerPrinted) {
                print(`\n  ── BUYER: ${buyerName || buyerVat}  →  CONTRACTOR: ${contractorName || contractorVat}`);
                headerPrinted = true;
                found = true;
            }

            const total = rows.reduce((s, r) => s + (r[2] || 0), 0);
            print(`\n  Procedure: ${pt || 'N/A'}  (${rows.length} awards, €${fmtN(total)} total)`);
            print('  ' + '#'.padStart(3) + '  ' + 'ADAM'.padEnd(20) + '  ' + 'Amount (€)'.padStart(14) + '  Subject');
            print('  ' + '─'.repeat(80));
            rows.forEach((r, i) => {
                print(
                    '  ' +
                    String(i + 1).padStart(3) + '.  ' +
                    (r[0] || '').padEnd(20) + '  ' +
                    fmtN(r[2]).padStart(14) + '  ' +
                    (r[3] || '').substring(0, 50)
                );
            });
        }
    }

    if (!found) print(`\n  No transactions found between ${vatA} and ${vatB}.`);
}

// ── VAT input loop ─────────────────────────────────────────────────────────────
function showVatSection(db, amountExpr) {
    print('');
    print('═'.repeat(70));
    print('  3. VAT LOOKUP');
    print('═'.repeat(70));
    print('');
    print("  Enter a VAT number to profile an organization.");
    print("  Enter VAT1-VAT2 to see all transactions between two parties.");
    print("  Type 'exit' or press Enter on empty to quit.");

    const inputRow = document.getElementById('input-row');
    const vatInput = document.getElementById('vat-input');

    inputRow.style.display = 'flex';
    vatInput.focus();

    function handleEnter(e) {
        if (e.key !== 'Enter') return;

        const entry = vatInput.value.trim();
        vatInput.value = '';

        print(`\n  > ${entry}`);

        if (!entry || entry.toLowerCase() === 'exit') {
            inputRow.style.display = 'none';
            print('\n  Session ended.');
            vatInput.removeEventListener('keydown', handleEnter);
            return;
        }

        try {
            if (entry.includes('-')) {
                const parts = entry.split('-', 2).map(s => s.trim());
                if (parts.length === 2 && parts[0] && parts[1]) {
                    lookupPair(db, parts[0], parts[1], amountExpr);
                } else {
                    print('  Invalid format. Use VAT1-VAT2 (e.g. 094079101-997997760).');
                }
            } else {
                lookupSingle(db, entry, amountExpr);
            }
        } catch (err) {
            print(`  Query error: ${err.message}`);
        }

        output.scrollTop = output.scrollHeight;
    }

    vatInput.addEventListener('keydown', handleEnter);
}

// ── Database loader with progress bar ─────────────────────────────────────────
async function loadDatabase(SQL) {
    const progressLine = printMutable('  Loading database...');

    const response = await fetch(DB_URL);
    const contentLength = response.headers.get('Content-Length');
    const total = contentLength ? parseInt(contentLength) : 0;
    const reader = response.body.getReader();
    const chunks = [];
    let loaded = 0;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;
        if (total) {
            const pct = Math.round(loaded / total * 100);
            const filled = Math.floor(pct / 5);
            const bar = '█'.repeat(filled) + '░'.repeat(20 - filled);
            progressLine.textContent = `  Loading database  ${bar}  ${pct}%\n`;
        }
    }

    // Reassemble chunks into a single Uint8Array
    const buffer = new Uint8Array(loaded);
    let pos = 0;
    for (const chunk of chunks) { buffer.set(chunk, pos); pos += chunk.length; }

    const sizeMb = (loaded / 1024 / 1024).toFixed(1);
    progressLine.textContent = `  Database loaded: ${sizeMb} MB  ✓\n`;

    return new SQL.Database(buffer);
}

// ── Main ───────────────────────────────────────────────────────────────────────
async function main() {
    print('╔' + '═'.repeat(68) + '╗');
    print('║  KIMDIS Analytics — Greek Public Procurement Data                   ║');
    print('║  github.com/DimitrisTsak/kimdis_analytics                           ║');
    print('╚' + '═'.repeat(68) + '╝');
    print('');
    print('  All data from the official KIMDIS open data API · Amounts excl. VAT');
    print('  Coverage: comprehensive for 2026, partial for 2025');
    print('');

    // Load sql.js engine
    let SQL;
    try {
        SQL = await initSqlJs({
            locateFile: file =>
                `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/${file}`
        });
    } catch (e) {
        print(`  Error loading sql.js: ${e.message}`);
        return;
    }

    // Load the database file
    let db;
    try {
        db = await loadDatabase(SQL);
    } catch (e) {
        print(`  Error loading database: ${e.message}`);
        print('');
        print('  For local testing:');
        print('    1. Copy kimdis_clean.db into this folder');
        print('    2. Run:  python -m http.server 8080');
        print('    3. Open: http://localhost:8080');
        return;
    }

    // Check if contractor_amount override column exists (may not in a fresh harvest)
    let amountExpr;
    try {
        db.exec('SELECT contractor_amount FROM award_contractors LIMIT 0');
        amountExpr = `CASE WHEN ac.contractor_amount IS NOT NULL
                           THEN ac.contractor_amount
                           ELSE a.total_cost_without_vat * 1.0 / cc.n END`;
    } catch (_) {
        amountExpr = `a.total_cost_without_vat * 1.0 / cc.n`;
    }

    section1(db);
    await sleep(0);
    await section2(db, amountExpr);
    await sleep(0);
    showVatSection(db, amountExpr);
}

main().catch(e => print(`\n  Fatal error: ${e.message}`));
