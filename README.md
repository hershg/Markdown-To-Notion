# Markdown-To-Notion
Script to convert Markdown files into Notion Documents.
Includes intelligent batching to get around Notion API restrictions, and pre-processing of the Markdown file to ensure newline LaTeX formatted equations (the ones surrounded by `$$` on either side) import as desired.

## Installation
### 1. Install `pymartian`
```
python3 -m pip install --upgrade pip
python3 -m pip install pymartian notion-client
```

### 2. Get Notion Token and save as environment variable
1. Go to https://www.notion.so/profile/integrations and create a new integration, and give it access to all your pages (Access tab)
2. Note the "Internal Integration Secret" (Configuration tab; will be of format `ntn_<...>`), and then add it to your bashrc environment as
```
export NOTION_TOKEN=ntn_<...>
```

### 3. Download and save this script
I saved it to `scripts/import_md_to_notion.py` on my machine

## User Guide
For a given Markdown document you wish to import into Notion, follow the following steps:
1. In Notion, make a new page. Note that if you make the new page at the root level, your Notion Integration you made in the previous step may not have access to it
2. From that new page, get its `page_id`. You can get this from the Notion page's share link (ex: if the share link is `https://www.notion.so/hershg/New-Page-12345678901234567890?source=copy_link` then `page_id` is `12345678901234567890`
3. Run the script `python3 scripts/import_md_to_notion.py -p <page_id> path/to/your/markdown/document`, and the script should be fully imported!
