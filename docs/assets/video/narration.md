# Sahifa explainer: narration (one paragraph per scene)

1. Every company runs on tables. Orders, customers, invoices, events. Thousands of them, in databases, warehouses and folders of files.

2. And data decays quietly. An order for a customer who doesn't exist. An IBAN with a broken check digit. A load that stopped in the night. Most tables were never tested, so nobody notices.

3. This is Sahifa. From the Arabic for a written sheet: the charter of Medina, which set down what each party could expect of the others. Sahifa does the same for your data.

4. Point it at a Postgres database or a folder of files. It profiles every column, writes the checks for you, twenty kinds today, from foreign keys to freshness, and scores what it finds. It only ever reads.

5. Every score comes with an honest error bar. A score from a sample tells you how sure it is, so you can tell a real drop from noise.

6. And every finding explains itself: how many rows, examples with personal values masked, the SQL that found them, and what to do next.

7. What to expect? Sahifa runs on your own machine, in about fifteen minutes. It never writes to your data, and it tells you if its login could. It's open source, and in preview. Test users are welcome.

8. Sahifa. Know what your data promises, and whether it keeps it.
