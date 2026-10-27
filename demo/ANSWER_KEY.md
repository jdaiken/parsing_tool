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
