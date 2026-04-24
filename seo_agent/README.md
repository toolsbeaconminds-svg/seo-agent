# SEO Agent

One-shot SEO analysis tool. Give it a URL, it produces a comprehensive markdown report.

## What it does

```
python main.py https://example.com
```

1. **Scout** — scrapes the site with Playwright, extracts business info with Claude, finds competitors via Ahrefs
2. **Data Collection** — pulls GSC, GA4, and Ahrefs data in parallel
3. **Analysis** — Claude synthesises everything into structured findings
4. **Report** — generates a markdown document in `output/`

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

Fill in `.env` with your API keys:
- `ANTHROPIC_API_KEY` — required
- `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` + `GA4_PROPERTY_ID` — for GSC/GA4 data
- `AHREFS_API_KEY` — for backlinks, keywords, competitors

If a data source is unavailable, the agent continues with what it has and notes the gap in the report.

## Output

The report is saved to `output/<business>_seo_analysis_<date>.md` and includes:
- Executive summary
- Traffic overview
- Findings by priority (critical → low)
- Keyword performance + opportunities
- Keyword gap analysis
- Competitor overview
- Quick wins
- Content recommendations
