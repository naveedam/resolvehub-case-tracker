"""
ResolveHub — merge split SBI cases
------------------------------------
One-off cleanup for cases that got wrongly split into separate rows because
clean_party_name() didn't originally handle SBI's dash-style document
suffixes ("NAME-T&C", "NAME-USP") — only the colon style. That's now fixed
in scraper.py for future runs; this script repairs cases already ingested
before the fix.

Purely operates against Supabase — makes NO requests to sbi.bank.in, so it's
safe to run repeatedly and doesn't add any load to their site.

Groups cases by (true borrower name, filing_date, summary). Any group with
more than one case is a split that should be one. For each group:
  - one case is picked as canonical (prefers one that already has a
    liability figure; otherwise the earliest-created)
  - documents and assets from duplicates are moved onto the canonical case
  - liabilities are moved onto canonical ONLY if it doesn't already have
    one (avoids double-counting the same debt); otherwise the duplicate's
    liability row is deleted
  - the canonical case's title is cleaned of any leftover suffix
  - duplicate case_parties and the duplicate case rows themselves are deleted

Run with dry_run=True first (default) to see what WOULD happen before
anything is changed.

Env vars required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import os
import re
from collections import defaultdict
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

SUFFIX_PATTERN = re.compile(
    r"[:\-]?\s*\b(USP|SALE\s*NOTICE|T\s*&\s*C|TERMS?\s*(AND|&)\s*CONDITIONS?"
    r"|PROPERTY|LOT\s*(NO\.?)?)\s*\d*\s*$",
    re.I,
)


def true_name(title: str) -> str:
    """Strips a trailing document-type suffix, looping so stacked suffixes
    (e.g. 'NAME PROPERTY 1:USP') get fully peeled off, not just the
    outermost one. Anchored at the END of the string (prevents 'T&C'
    inside 'MEAT & CHICKEN' from matching) and requires a word boundary
    before the keyword (prevents 'LOT' matching inside 'PLOT'). Allows an
    optional trailing number (USP 401, T&C1). Never returns an empty
    string — if stripping would blank the name entirely, keeps the last
    non-empty version instead."""
    current = title
    while True:
        stripped = SUFFIX_PATTERN.sub("", current).strip()
        if not stripped or stripped == current:
            break
        current = stripped
    return current if current else title


def fetch_all_sbi_cases() -> list[dict]:
    """Paginated fetch so this works regardless of the project's Max Rows setting."""
    all_cases = []
    offset = 0
    page_size = 1000
    while True:
        resp = (
            supabase.table("cases")
            .select("*")
            .is_("deleted_at", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data
        if not batch:
            break
        all_cases.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return [c for c in all_cases if (c.get("metadata") or {}).get("source") == "SBI"]


def build_merge_groups(cases: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for c in cases:
        key = (true_name(c["title"]), c.get("filing_date"), c.get("summary"))
        groups[key].append(c)
    return {k: v for k, v in groups.items() if len(v) > 1}


def clean_standalone_titles(cases: list[dict], merge_groups: dict, dry_run: bool) -> int:
    """Cases with a leftover dash-suffix in the title that were NEVER part
    of a merge group — these are notices that only ever had one document
    (no sibling to split from), but the old buggy clean_party_name() still
    failed to strip the suffix when the title was first set. Just clean
    the title in place; no merging needed since there's only one case."""
    merged_ids = {c["id"] for group in merge_groups.values() for c in group}
    dirty = [c for c in cases if c["id"] not in merged_ids and true_name(c["title"]) != c["title"]]

    print(f"\nFound {len(dirty)} standalone cases with a leftover dirty title (no merge needed, just cleanup)")
    if dry_run:
        for c in dirty[:15]:
            print(f"  '{c['title']}' -> '{true_name(c['title'])}'")
        if len(dirty) > 15:
            print(f"  ...and {len(dirty) - 15} more")
        return len(dirty)

    for c in dirty:
        supabase.table("cases").update({"title": true_name(c["title"])}).eq("id", c["id"]).execute()
    return len(dirty)


def repair_titles_from_documents(dry_run: bool = True):
    """Recomputes every SBI case's title from its linked document's
    ORIGINAL document_name (never touched by any title-cleaning regex,
    past or present) and fixes any mismatch. This is the authoritative
    repair — it doesn't rely on remembering which specific cases a past
    bug affected, it just re-derives the truth from the untouched source."""
    print("Fetching all SBI cases and their documents...")
    cases = fetch_all_sbi_cases()
    case_by_id = {c["id"]: c for c in cases}

    all_docs = []
    offset = 0
    page_size = 1000
    while True:
        resp = supabase.table("documents").select("case_id, document_name").range(offset, offset + page_size - 1).execute()
        batch = resp.data
        if not batch:
            break
        all_docs.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Use the first document found per case as the source of truth
    first_doc_by_case: dict[str, str] = {}
    for d in all_docs:
        if d["case_id"] in case_by_id and d["case_id"] not in first_doc_by_case:
            first_doc_by_case[d["case_id"]] = d["document_name"]

    mismatches = []
    for case_id, doc_name in first_doc_by_case.items():
        if not doc_name:
            continue
        correct_name = re.sub(r"^\d+\.\s*", "", doc_name)
        correct_name = re.sub(r"\([\d.]+\s*[KM]?B\)\s*$", "", correct_name)
        correct_name = true_name(correct_name)
        current_title = case_by_id[case_id]["title"]
        if correct_name and correct_name != current_title:
            mismatches.append((case_id, current_title, correct_name))

    print(f"\nFound {len(mismatches)} cases whose title doesn't match their source document label")
    if dry_run:
        for case_id, before, after in mismatches[:30]:
            print(f"  '{before}' -> '{after}'")
        if len(mismatches) > 30:
            print(f"  ...and {len(mismatches) - 30} more")
        print("\nRun repair_titles_from_documents(dry_run=False) to apply.")
        return

    for case_id, before, after in mismatches:
        supabase.table("cases").update({"title": after}).eq("id", case_id).execute()
    print(f"Repaired {len(mismatches)} case titles.")


def build_exact_liability_groups(cases: list[dict]) -> dict[tuple, list[dict]]:
    """Groups by (title, estimated_liability) exactly. Two cases with the
    identical dollar-for-dollar liability figure are effectively certain
    to be the same real case, re-ingested across different scrape
    sessions where the underlying description/date text drifted slightly
    (SBI's page 1 content isn't a stable snapshot - it can shift between
    runs). This catches duplication the suffix/title-based grouping
    missed, including near-identical name typos across sessions."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for c in cases:
        if c.get("estimated_liability") is None:
            continue  # no reliable second key to group on for null-liability cases
        key = (c["title"].strip().upper(), round(c["estimated_liability"], 2))
        groups[key].append(c)
    return {k: v for k, v in groups.items() if len(v) > 1}


def merge_group_list(merge_groups: dict, dry_run: bool) -> int:
    """Shared merge machinery - same logic as run()'s merge loop, reused
    here for the exact-liability grouping."""
    if dry_run:
        for key, group in list(merge_groups.items())[:20]:
            name, amount = key
            print(f"  MERGE ({len(group)} cases) -> '{name}' (Rs.{amount:,.2f})")
        if len(merge_groups) > 20:
            print(f"  ...and {len(merge_groups) - 20} more groups")
        return sum(len(v) - 1 for v in merge_groups.values())

    merged_count = 0
    for key, group in merge_groups.items():
        group.sort(key=lambda c: (c.get("estimated_liability") is None, c["created_at"]))
        canonical = group[0]
        duplicates = group[1:]
        canonical_id = canonical["id"]

        for dup in duplicates:
            dup_id = dup["id"]
            supabase.table("documents").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()
            supabase.table("assets").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()

            canon_liabs = supabase.table("liabilities").select("id").eq("case_id", canonical_id).execute().data
            if not canon_liabs:
                supabase.table("liabilities").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()
            else:
                supabase.table("liabilities").delete().eq("case_id", dup_id).execute()

            supabase.table("case_parties").delete().eq("case_id", dup_id).execute()
            supabase.table("cases").delete().eq("id", dup_id).execute()

        merged_count += 1
        if merged_count % 50 == 0:
            print(f"  merged {merged_count}/{len(merge_groups)} groups...")

    return merged_count


def run_exact_liability_merge(dry_run: bool = True):
    print("Fetching all SBI cases...")
    cases = fetch_all_sbi_cases()
    print(f"  {len(cases)} total SBI cases")

    merge_groups = build_exact_liability_groups(cases)
    total_dupes = sum(len(v) - 1 for v in merge_groups.values())
    print(f"Found {len(merge_groups)} exact-liability duplicate groups, "
          f"removing {total_dupes} duplicate case rows\n")

    if dry_run:
        print("--- DRY RUN: no changes will be made ---\n")
        merge_group_list(merge_groups, dry_run=True)
        print("\nRun with dry_run=False to actually apply these merges.")
        return

    merged_count = merge_group_list(merge_groups, dry_run=False)
    print(f"\nDone. Merged {merged_count} groups, removed {total_dupes} duplicate case rows.")


def run(dry_run: bool = True):
    print("Fetching all SBI cases..." )
    cases = fetch_all_sbi_cases()
    print(f"  {len(cases)} total SBI cases")

    merge_groups = build_merge_groups(cases)
    total_dupes = sum(len(v) - 1 for v in merge_groups.values())
    print(f"Found {len(merge_groups)} groups to merge, removing {total_dupes} duplicate case rows\n")

    if dry_run:
        print("--- DRY RUN: no changes will be made ---\n")
        for key, group in list(merge_groups.items())[:15]:
            name, filing_date, _ = key
            print(f"  MERGE ({len(group)} cases) -> '{name}' filed {filing_date}")
        if len(merge_groups) > 15:
            print(f"  ...and {len(merge_groups) - 15} more groups")
        clean_standalone_titles(cases, merge_groups, dry_run=True)
        print("\nRun with dry_run=False to actually apply these merges + title cleanups.")
        return

    merged_count = 0
    for key, group in merge_groups.items():
        name, _, _ = key
        # Prefer a case that already has a liability figure as canonical;
        # tie-break on earliest created_at.
        group.sort(key=lambda c: (c.get("estimated_liability") is None, c["created_at"]))
        canonical = group[0]
        duplicates = group[1:]
        canonical_id = canonical["id"]

        clean_title = true_name(canonical["title"])
        if clean_title != canonical["title"]:
            supabase.table("cases").update({"title": clean_title}).eq("id", canonical_id).execute()

        for dup in duplicates:
            dup_id = dup["id"]

            supabase.table("documents").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()
            supabase.table("assets").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()

            canon_liabs = supabase.table("liabilities").select("id").eq("case_id", canonical_id).execute().data
            if not canon_liabs:
                supabase.table("liabilities").update({"case_id": canonical_id}).eq("case_id", dup_id).execute()
                if canonical.get("estimated_liability") is None and dup.get("estimated_liability") is not None:
                    supabase.table("cases").update(
                        {"estimated_liability": dup["estimated_liability"]}
                    ).eq("id", canonical_id).execute()
                    canonical["estimated_liability"] = dup["estimated_liability"]
            else:
                supabase.table("liabilities").delete().eq("case_id", dup_id).execute()

            supabase.table("case_parties").delete().eq("case_id", dup_id).execute()
            supabase.table("cases").delete().eq("id", dup_id).execute()

        merged_count += 1
        if merged_count % 25 == 0:
            print(f"  merged {merged_count}/{len(merge_groups)} groups...")

    print(f"\nDone. Merged {merged_count} groups, removed {total_dupes} duplicate case rows.")

    cleaned = clean_standalone_titles(cases, merge_groups, dry_run=False)
    print(f"Cleaned {cleaned} standalone dirty titles.")


if __name__ == "__main__":
    run(dry_run=True)  # flip to dry_run=False after reviewing the output