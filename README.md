# NIH Funding Radar

A zero-database, daily funding monitor tailored to the Johnson Lab. It combines:

- active and forecasted NIH opportunities from the official Grants.gov API;
- NIH Guide notices from the official NIH RSS feed;
- NIH Highlighted Topics monitoring;
- transparent keyword/topic scoring, exclusions, and institute boosts;
- a responsive static HTML feed with search, source/topic filters, and “new only.”

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python update_feed.py
python -m http.server 8000 --directory docs
```

Open `http://localhost:8000`. To preview without network access, run `python update_feed.py --demo`.

## Publish and update every day

1. Create an empty GitHub repository and put the contents of this folder at its root.
2. In **Settings → Pages**, choose **Deploy from a branch**, branch `main`, folder `/docs`.
3. In **Settings → Actions → General**, give workflows **Read and write permissions**.
4. Run **Actions → Update NIH funding feed → Run workflow** once. GitHub then runs it daily.

No API key or paid service is required. The schedule is UTC; edit `.github/workflows/update.yml` to change it.

## Customize relevance

Edit `config.json`:

- add or remove phrases under each keyword group;
- adjust `minimum_score` (higher means fewer, tighter matches);
- edit priority institutes and exclusions;
- change the feed title and lookback window.

Matches are phrase-based and fully auditable. A matched group earns points, additional terms add points, priority institutes add two, and targeted mechanisms add one. Exclusions subtract five each.

## Reliability notes

- A failure in one source does not erase results from the others; it appears as a warning on the page.
- `data/state.json` records first-seen dates so the “new” label survives daily runs.
- NIH Highlighted Topics are currently client-rendered. The collector parses rows when available and otherwise monitors the official page as a linked update item.
- Opportunity details and deadlines should always be confirmed on the linked official notice before planning an application.

## Test

```bash
python -m unittest discover -s tests -v
```
