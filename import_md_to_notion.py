import os
import sys
import argparse
import time
from notion_client import Client
from martian import markdown_to_blocks
import re

FENCE_RE = re.compile(r"^(\s*)(```|~~~)")
SINGLELINE_DBLDOLLAR_RE = re.compile(r"^(\s*)\$\$(.+?)\$\$\s*$")
ONLY_DBLDOLLAR_RE = re.compile(r"^(\s*)\$\$\s*$")


def preprocess_display_math(md: str) -> str:
    """
    Ensures display-math written with $$...$$ becomes a standalone block by:
      - inserting a blank line before/after display math blocks when missing
      - rewriting single-line $$ expr $$ into:
            $$
            expr
            $$
    Preserves indentation (important for list items).
    Skips fenced code blocks entirely.
    """
    lines = md.splitlines(True)  # keep newlines
    out = []

    in_fence = False
    fence_marker = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Toggle fenced code blocks
        m_fence = FENCE_RE.match(line)
        if m_fence:
            marker = m_fence.group(2)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None

            out.append(line)
            i += 1
            continue

        if in_fence:
            out.append(line)
            i += 1
            continue

        # Case 1: single-line $$...$$
        m_single = SINGLELINE_DBLDOLLAR_RE.match(line)
        if m_single:
            indent = m_single.group(1)
            expr = m_single.group(2).strip()

            # ensure blank line before (preserve indent for list context)
            if out and out[-1].strip() != "":
                out.append(indent + "\n")

            # rewrite to multiline block math
            out.append(f"{indent}$$\n")
            out.append(f"{indent}{expr}\n")
            out.append(f"{indent}$$\n")

            # ensure blank line after if next line is non-blank
            if i + 1 < len(lines) and lines[i + 1].strip() != "":
                out.append(indent + "\n")

            i += 1
            continue

        # Case 2: multi-line math delimited by lines that are exactly "$$"
        m_open = ONLY_DBLDOLLAR_RE.match(line)
        if m_open:
            indent = m_open.group(1)

            if out and out[-1].strip() != "":
                out.append(indent + "\n")

            # copy through closing "$$"
            out.append(line)
            i += 1
            while i < len(lines):
                out.append(lines[i])
                if ONLY_DBLDOLLAR_RE.match(lines[i]):
                    i += 1
                    break
                i += 1

            if i < len(lines) and lines[i].strip() != "":
                out.append(indent + "\n")

            continue

        # Default: unchanged
        out.append(line)
        i += 1

    return "".join(out)


def chunk(lst, n=100):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main():
    parser = argparse.ArgumentParser(
        description="Import a local Markdown (.md) file into a Notion page using pymartian + notion-client."
    )
    parser.add_argument(
        "md_path",
        help="Path to the Markdown file to import",
    )
    parser.add_argument(
        "-p",
        "--page-id",
        required=True,
        help="Target Notion page ID (with or without hyphens). Can get this from the shareable link of a page",
    )
    parser.add_argument("--token-env", default="NOTION_TOKEN", help="Env var for Notion token (default: NOTION_TOKEN)")
    parser.add_argument("--batch-size", type=int, default=100, help="Blocks per request (max: 100)")
    parser.add_argument("--sleep", type=float, default=0.35, help="Sleep between successful requests (default: 0.35s)")
    parser.add_argument("--start", type=int, default=0, help="Skip the first N blocks (useful to resume)")
    parser.add_argument("--max-retries", type=int, default=1, help="Max retries on transient failures (default: 1)")
    parser.add_argument("--skip-bad-blocks", action="store_false", help="Skip a single bad block instead of aborting")

    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 100:
        print("Error: --batch-size must be between 1 and 100.")
        sys.exit(1)

    token_env = args.token_env
    if token_env not in os.environ:
        print(f"Error: environment variable {token_env} is not set. Example: export {token_env}='secret_...'")
        sys.exit(1)

    md_path = args.md_path
    page_id = args.page_id

    notion = Client(auth=os.environ[token_env])

    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()
    md = preprocess_display_math(md)

    limit_errors = []
    def on_limit_error(err):
        limit_errors.append(err)
        # print the first few to understand what's going on
        if len(limit_errors) <= 5:
            print("Notion limit issue:", err)

    options = {
        "notionLimits": {
            "truncate": False,   # disable truncation :contentReference[oaicite:1]{index=1}
            "onError": on_limit_error,  # log limit-related errors :contentReference[oaicite:2]{index=2}
        }
    }

    blocks = markdown_to_blocks(md, options)   # note: pass options as 2nd positional arg
    total = len(blocks)
    print(f"\nConverted markdown -> {total} blocks")

    print("  limit_errors:", len(limit_errors))
    for err in limit_errors:
        print(f"    {err}")
    print("  last_block_type:", blocks[-1].get("type"))
    print("  last_block_preview:", str(blocks[-1])[:300])

    start = max(0, min(args.start, total))
    i = start
    batch_size = args.batch_size

    def append_batch(children):
        notion.blocks.children.append(block_id=args.page_id, children=children)

    while i < total:
        # Never exceed Notion's max 100 children array limit. :contentReference[oaicite:5]{index=5}
        batch_size = min(batch_size, 100)
        batch = blocks[i : i + batch_size]

        retries = 0
        while True:
            try:
                append_batch(batch)
                i += len(batch)
                print(f"✅ Appended {i}/{total} blocks")
                time.sleep(args.sleep)
                break

            except APIResponseError as e:
                # Rate limit: honor Retry-After header if present. :contentReference[oaicite:6]{index=6}
                if getattr(e, "status", None) == 429 or getattr(e, "code", "") == "rate_limited":
                    retry_after = None
                    try:
                        retry_after = int(e.headers.get("Retry-After"))
                    except Exception:
                        retry_after = None
                    wait = retry_after if retry_after is not None else min(2 ** retries, 30)
                    print(f"⏳ Rate limited. Waiting {wait}s then retrying...")
                    time.sleep(wait)
                    retries += 1
                    if retries > args.max_retries:
                        raise
                    continue

                # Validation/payload issues: shrink batch and retry (often fixes 500KB payload issues). :contentReference[oaicite:7]{index=7}
                if getattr(e, "status", None) == 400 or getattr(e, "code", "") == "validation_error":
                    if len(batch) == 1:
                        msg = f"❌ Block {i} failed validation: {str(e)}"
                        if args.skip_bad_blocks:
                            print(msg + " — skipping it.")
                            i += 1
                            break
                        raise RuntimeError(msg) from e

                    batch_size = max(1, batch_size // 2)
                    batch = blocks[i : i + batch_size]
                    print(f"⚠️ Validation/payload error. Reducing batch size to {batch_size} and retrying...")
                    retries += 1
                    if retries > args.max_retries:
                        raise
                    continue

                # Other API errors
                raise

            except RequestTimeoutError:
                wait = min(2 ** retries, 30)
                print(f"⏳ Request timed out. Waiting {wait}s then retrying...")
                time.sleep(wait)
                retries += 1
                if retries > args.max_retries:
                    raise

    print(f"🎉 Done. Appended {total - start} blocks to page {args.page_id} (skipped first {start}).")

if __name__ == "__main__":
    main()
