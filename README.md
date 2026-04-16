# Bluesky Alt Text Dataset

279,196 image alt-text pairs from 489 Bluesky accounts, collected via the public AT Protocol APIs. Every account in the dataset was validated to have a 90%+ alt-text rate with substantive descriptions — this is a corpus of what good alt text looks like.

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)

## At a glance

| | |
|---|---|
| **Rows** | 279,196 (one per image, not per post) |
| **Authors** | 489 unique accounts |
| **Mean alt text length** | 203 characters |
| **Median alt text length** | 127 characters |
| **Rows >100 characters** | 168,980 (60.5%) |
| **Languages** | Primarily English (85%), plus German, French, Portuguese, and others |
| **Format** | JSONL (gzipped), CSV (gzipped) |
| **License** | CC-BY 4.0 |
| **Collection date** | April 2026 |

## Download

Grab the compressed files from the [latest release](https://github.com/data-poems/bluesky-alt-text/releases/latest):

- `corpus.jsonl.gz` (89 MB) — one JSON object per line
- `corpus.csv.gz` (77 MB) — same data, flat format

## Schema

Each row represents one image with alt text. A post with 4 images produces 4 rows.

| Field | Type | Description |
|---|---|---|
| `alt_text` | string | The image description written by the author |
| `image_alt_length` | int | Character count of the alt text |
| `text` | string | Post body text |
| `author_handle` | string | Bluesky handle (e.g. `tink.uk`) |
| `author_did` | string | Decentralized identifier |
| `post_uri` | string | AT Protocol post URI |
| `post_cid` | string | Content identifier (hash) |
| `created_at` | string | When the post was written (ISO 8601) |
| `indexed_at` | string | When the post was indexed (ISO 8601) |
| `langs_json` | string | JSON array of language tags |
| `image_index` | int | Position of this image in the post (0-based) |
| `image_count_in_post` | int | Total images in the post |
| `image_mime_type` | string | MIME type (`image/jpeg`, etc.) |
| `image_ref` | string | Blob reference hash |
| `image_thumb_url` | string | CDN thumbnail URL |
| `image_fullsize_url` | string | CDN full-size URL |
| `source_mode` | string | Always `author_feed` for this corpus |
| `collected_at` | string | When this row was collected (ISO 8601) |
| `query` | string | Which actor this row came from |
| `cursor` | string | API pagination cursor (for provenance) |
| `raw_record_json` | string | Complete AT Protocol record as JSON |

## Quick start

```python
import json

with open("corpus.jsonl") as f:
    for line in f:
        row = json.loads(line)
        print(f"{row['author_handle']}: {row['alt_text'][:80]}...")
```

Or load into pandas:

```python
import pandas as pd

df = pd.read_json("corpus.jsonl", lines=True)
df["alt_text"].str.len().describe()
```

See [`explore.ipynb`](explore.ipynb) for a full walkthrough with visualizations.

## How accounts were selected

This is not a random sample. Every account was found through one of eight discovery strategies, then validated against the live Bluesky API.

**Discovery:**
1. Accounts highlighted by the [Alt Text Hall of Fame](https://bsky.app/profile/alttexthof.bsky.social)
2. Social graph of the Hall of Fame (who they follow, who follows them)
3. Accessibility keyword search (`searchActors` for "alt text", "a11y", "WCAG", etc.)
4. Network tracing from 8 accessibility seed accounts
5. International accessibility search (German, French, Portuguese, Japanese, Spanish, Dutch, Swedish)
6. Institutional search (museums, zoos, aquariums, space agencies, botanical gardens)
7. Photography and visual arts accounts
8. Jetstream firehose sampling for wild-caught alt text writers

**Validation gate (every account must pass all three):**
- 90%+ of their images have non-empty alt text
- Average alt text length of 50+ characters
- At least 10 images to confirm the pattern holds

The full account list is in [`collector/actors.txt`](collector/actors.txt).

## What's in here

```
corpus.jsonl.gz          # The dataset (279K rows, 89 MB compressed)
corpus.csv.gz            # Same data in CSV format (77 MB compressed)
explore.ipynb            # Jupyter notebook: load, explore, visualize
collector/               # The tool that built this dataset
  bluesky_alt_text_scraper.py
  actors.txt
  requirements.txt
LICENSE                  # CC-BY 4.0
```

## Use cases

- **Training alt text generators**: Fine-tune vision-language models on high-quality human-written descriptions
- **Benchmarking**: Compare generated alt text against this corpus for quality evaluation
- **Accessibility research**: Study how people describe images for screen reader users
- **Style analysis**: Explore description patterns across museums, photographers, scientists, advocates
- **Contrastive training**: Pair with a firehose sample (included in the collector) to learn what distinguishes good alt text from minimal effort

## Citation

```bibtex
@dataset{steuber2026blueskyalttext,
  title     = {Bluesky Alt Text Dataset},
  author    = {Steuber, Luke},
  year      = {2026},
  url       = {https://github.com/data-poems/bluesky-alt-text},
  license   = {CC-BY-4.0},
  note      = {279,196 image alt-text pairs from 489 validated Bluesky accounts}
}
```

## License

[CC-BY 4.0](LICENSE). Use it for anything — just credit the source.

The alt text in this dataset was written by Bluesky users and is collected from public posts via Bluesky's documented APIs. No private data, no scraping, no authentication required.
