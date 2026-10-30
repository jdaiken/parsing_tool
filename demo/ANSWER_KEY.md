# Demo case: the Hartwell accounts (answer key)

Everything in this folder is fictional: the bank (Larkspur Valley Bank, larkspurvalleybank.example), the customer, the caregiver, the account numbers and every transaction. Each page carries a red "SAMPLE STATEMENT, FICTIONAL DATA" banner. `make_demo_case.py` rebuilds the files.

## The story

Evelyn Hartwell is a retired widow in Maple Grove, Iowa, living on a pension and Social Security. In April a paid caregiver, Dana Pruitt (who bills through "DP Companion Care LLC"), gets access to her checkbook, debit card and online banking. Over two months the account goes from about $16,000, plus a $50,000 CD that matures in April, to overdrawn.

Her family asks for the statements. The caregiver gives them a "family copy" of April that looks fine.

## The files

| File | What it is |
| --- | --- |
| `1_checking_2025-03.pdf` | March checking. Normal activity; this is the baseline. |
| `2_checking_2025-04.pdf` | April checking. The exploitation starts. |
| `3_checking_2025-05.pdf` | May checking. The account is drained. |
| `4_credit_card_2025-05.pdf` | May credit card. Gift cards and casino cash advances. |
| `5_checking_2025-04_family_copy.pdf` | The doctored April the caregiver showed the family. |
| `6_checking_2025-05_scanned_redacted.pdf` | A printed-and-scanned copy of May with the account number, name and address blacked out. |

In the app, **Try it with sample statements** loads files 1 to 4. **Try a doctored statement** loads the genuine April next to the family copy. To show OCR, drag file 6 into the version that runs on your computer (the in-browser version can't read scans).

## Fraud patterns planted (Red Flags tab, "Fraud patterns found")

| Planted | Where | What the app reports |
| --- | --- | --- |
| A new payee taking large sums | Checks 2043, 2044, 2047, 2048 and a $24,000 wire to DP Companion Care LLC, none before April | New payee: Dp Companion Care, 5 payments, $29,400 |
| Zelle payments to the caregiver | $500, $1,000, $2,000, $1,500 to Dana Pruitt | New payee: Dana Pruitt, $5,000; round-dollar transfers |
| CD proceeds moved straight out | $50,000 CD maturity on 04/14, $24,000 wired out on 04/15 | Account balance drained (the peak is the CD deposit) |
| Cash kept under $10,000 | Branch withdrawals of $9,500, $9,800, $9,000 and $5,080 | Cash withdrawals kept just under $10,000 (structuring) |
| Cash spike | March: $100 in cash. April: $20,703.50. May: $15,587 | Cash withdrawals jumped in April 2025 / May 2025 |
| Gambling | Lucky Star Casino ATM withdrawals (mostly weekends) and card cash advances | Gambling or casino activity, on both the checking and the card |
| Gift cards | Target and Walgreens gift cards on the debit card; Google Play, Vanilla and Apple gift cards on the credit card | Gift card purchases, on both accounts |
| Card cash advances | $1,000 and $500 at the casino | Credit card cash advances |
| Duplicate payment | Checks 2043 and 2044, $1,200 each, a day apart | Possible duplicate payment to Dp Companion Care |
| Missing checks | Checks 2045 and 2046 never clear | Check sequence gap (All flags table) |
| The account runs dry | Overdraft fee 05/28, returned check 2049 on 05/29; May ends at -$79.93 | Overdraft or returned-item fees; Account balance drained |

All four genuine statements reconcile on the Bank Reconciliation tab, and the scanned copy reconciles too once read with OCR.

## Edits planted in the family copy (Document Check tab)

The family copy removes the casino, wire, cash and CD lines and renames the caregiver's checks "MAPLE GROVE HOME HEALTH". The edits leave these traces, and the app reports all nine:

| Planted | What the app reports |
| --- | --- |
| Saved with iLovePDF | Software that made the PDF: a PDF editing tool |
| Created 05/02/2025, saved again 06/23/2025 | Saved again after it was created, 52 days later |
| Edited lines typed in Times; the rest of the statement is Helvetica | Fonts on transaction lines: 4 lines in a different font |
| A 05/02 purchase pasted into April | Dates inside the statement period |
| The 04/22 AARP premium moved below 04/25 | Transactions in date order |
| "ZELLE PAYMENT **TO** DANA PRUITT" changed to "**FROM**", still money out | Descriptions match money in and out |
| One balance retyped $1,000 too high (check 2043) | Running balances add up: breaks at checks 2043 and 2044 |
| Summary deposits inflated by $1,500 | Summary agrees with the transactions: off by $1,500.00 |
| Ending balance typed as "$13763.86", with no comma | Amounts formatted consistently |

The family copy also shows **Variance** on the Bank Reconciliation tab.

Teaching point: none of these proves fraud on its own, and a clean result doesn't prove a statement is genuine. When a statement matters, get it directly from the bank, or by subpoena.

## Things to try live

- Compare the Dashboard's cash-flow and balance charts for March with April and May.
- Filter the Transactions tab for "Lucky Star" or "Pruitt".
- Download the workpaper. The Flags_For_Review sheet lists every pattern, and the Document_Checks sheet lists every document check.

---

# The full case: three more banks, the case documents and an AI-generated statement

`make_case_pack.py` builds these. Like everything here, the banks (Quillbrook Credit Union, Oxbow Prairie National Bank, Wrenfield Trust Bank), the law firms, the people and the numbers are invented, and each page carries the SAMPLE banner.

## More statements

| File | What it is | Layout (so students see more than one) |
| --- | --- | --- |
| `7_dp_companion_care_2025-04.pdf`, `8_..._2025-05.pdf` | DP Companion Care LLC business checking at Quillbrook Credit Union (subpoenaed) | Separate Withdrawals and Deposits columns, running balance |
| `9_pruitt_personal_2025-04.pdf`, `10_..._2025-05.pdf` | Dana Pruitt's personal checking at Oxbow Prairie National Bank (subpoenaed) | Sections by type with totals, no running balance, daily balance table, two pages |
| `11_wrenfield_repayment_proof_2025-05.pdf` | The "proof of repayment" Dana's attorney sent (Exhibit I). Written by an AI tool | Simple one-page table |

All four genuine statements read cleanly and reconcile. In the app, **Try the full case** loads files 1 to 4 and 7 to 10; **Try an AI-generated statement** loads file 11 next to Evelyn's genuine May statement.

## Case documents (`case_documents/`)

| Exhibit | Document | What it gives the student |
| --- | --- | --- |
| A | Engagement letter from Brennan & Thale Elder Law | The five questions to answer, the document list, the deadline, and the limits (no conclusions on intent) |
| B | Interview notes with Laura Byrne (daughter, POA) | Dana's phone number (319) 555-0188; Evelyn never used online banking and never lent money; the new SUV; checks 2045 and 2046 missing |
| C | Caregiver services agreement | $24/hour, M/W/F 9 to 1 (12 hours a week), paid by check against invoices; no loans, gifts, or use of Evelyn's cards, checks or online banking |
| D | Invoice INV-1001 | The only invoice: 24 hours, $576.00, for April 1 to 13 |
| E | CD maturity notice | $50,000 CD ending 5521 matures 04/14/2025, instructions: move it to checking |
| F | Larkspur account change confirmation, 04/03/2025 | Phone on file changed from Evelyn's landline to **Dana's cell**; email added; online banking enrolled |
| G | Outgoing wire confirmation | $24,000 on 04/15 to DP Companion Care LLC at Quillbrook, account 70033390; passcode texted to **Dana's cell**; a new iPhone first seen 04/03 |
| H | Check images | Checks 2043, 2044, 2047 and 2048 endorsed for mobile deposit to Quillbrook account 70033390. 2043/2044 are signed "Evelyn R. Hartwell"; **2047/2048 are signed "Evelyn Hartwell" in a different hand**, and 2047's memo says "advance". The LLC's check 1001: $18,750 to Ambrose Lane Motors, memo "SUV down pmt - D. Pruitt" |
| I | Letter from Dana's attorney | Claims the wire was a loan, repaid $10,000 on 05/06 and $14,000 on 05/20 from Wrenfield Trust Bank; checks were wages; Zelle was reimbursement |

## Tracing the money (answers to the engagement questions)

**1. Where the money went**

| From Evelyn's accounts | Amount | Where it went (evidence) |
| --- | --- | --- |
| Checks 2043, 2044, 2047, 2048 | $5,400.00 | Deposited to the LLC at Quillbrook one to three days before each cleared Evelyn's account (files 7-8, Exhibit H) |
| Wire 04/15 | $24,000.00 | The LLC at Quillbrook (file 7, Exhibit G); $18,750 left the next day as check 1001 for Dana's SUV |
| Zelle to Dana Pruitt | $5,000.00 | Dana's Oxbow account the same day (files 9-10) |
| Branch cash withdrawals | $33,380.00 | Dana deposited $9,000, $9,500, $8,500 and $4,800 cash one to four days after each withdrawal: $31,800.00 (files 9-10) |
| Casino ATM, card cash advances, gift cards | about $6,600 plus fees | Can't be traced from these records. Evelyn no longer drives; Dana's own card was at the same casino on 04/12, 04/19 and 05/03 |

Out of the LLC: $8,000 to Dana's personal account, $18,750 for the SUV, $612.30 car loan payment. No payroll, insurance or other clients: the LLC looks like a pass-through. Dana's balance went from $1,842.17 to $34,059.68; her only income not traceable to Evelyn is $492.02 from DoorDash.

**2. Supported by the agreement and invoices:** $576.00 (Exhibit D). Even if every scheduled visit from April 1 to May 31 happened (26 visits of 4 hours), the most earned would be $2,496.00. Paid to the LLC and Dana: $34,400.00.

**3. The cash:** $31,800 of the $33,380 reappears as cash deposits in Dana's account, each just under $10,000, the same structuring pattern seen on the withdrawal side (the app flags both).

**4. The two questioned statements:**
- The family copy (file 5): nine signs of editing (see above).
- The Wrenfield statement (file 11): the Document Check reports it as **possibly AI-generated** (4 signs): made with ReportLab with its default "anonymous" author; a leftover markdown heading `**Account Summary**`; a statement date of 06/31/2025, which doesn't exist; and routing number 073905528, which fails the check digit. Also: "Page 1 of 2" on a one-page file, a running balance that doesn't add up, and the account number printed as ...4417 and ...4471. The content fails too: Evelyn's genuine May statement shows **no deposits** from Dana or Wrenfield on or after 05/06 or 05/20; Dana's Oxbow statements show no transfers to any Wrenfield account; and the "Payroll Deposit - DP Companion Care LLC $3,200" doesn't appear on the LLC's May statement. The file was created 09/12/2025, the day of the attorney's letter.

**5. Amount without documented authorization (one defensible answer):** $34,400.00 paid to the LLC and Dana, less $576.00 invoiced = **$33,824.00** directly traced. Plus $31,800.00 of cash traced to Dana's deposits, for **$65,624.00** traced to Dana or her company. The casino, cash advance and gift card amounts are unexplained but not traced. Students should state that the checks' signatures need a questioned-document examiner, and that intent is for the court.

## Fraud patterns the app reports across the full case

On top of Evelyn's patterns above: **Cash deposits kept just under $10,000** (Dana, Oxbow), **Money in and straight back out** ($24,000 into the LLC, 91% gone within 3 days), **Account balance drained** (the LLC), casino activity on Dana's card, new payees (Sunwave Cruises, Maple Grove Jewelers), and round-dollar transfers from the LLC to Dana.
