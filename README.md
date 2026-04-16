---
license: cc-by-4.0
task_categories:
  - image-to-text
  - text-generation
  - text-classification
language:
  - en
  - de
  - fr
  - pt
tags:
  - bluesky
  - alt-text
  - accessibility
  - image-description
  - at-protocol
  - a11y
  - screen-reader
  - vision-language
pretty_name: "Bluesky Alt Text: 279K Curated Image Descriptions"
size_categories:
  - 100K<n<1M
dataset_info:
  features:
    - name: alt_text
      dtype: string
    - name: image_alt_length
      dtype: int64
    - name: text
      dtype: string
    - name: author_handle
      dtype: string
    - name: author_did
      dtype: string
    - name: post_uri
      dtype: string
    - name: post_cid
      dtype: string
    - name: created_at
      dtype: string
    - name: indexed_at
      dtype: string
    - name: langs_json
      dtype: string
    - name: image_index
      dtype: int64
    - name: image_count_in_post
      dtype: int64
    - name: image_mime_type
      dtype: string
    - name: image_ref
      dtype: string
    - name: image_thumb_url
      dtype: string
    - name: image_fullsize_url
      dtype: string
    - name: source_mode
      dtype: string
    - name: collected_at
      dtype: string
    - name: query
      dtype: string
    - name: cursor
      dtype: string
    - name: raw_record_json
      dtype: string
---

# Bluesky Alt Text: 279K Curated Image Descriptions

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightblue.svg)](https://creativecommons.org/licenses/by/4.0/)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Dataset-FFD21E)](https://huggingface.co/datasets/lukeslp/bluesky-alt-text)
[![GitHub](https://img.shields.io/badge/GitHub-Repo-181717)](https://github.com/data-poems/bluesky-alt-text)
[![Rows](https://img.shields.io/badge/rows-279,196-blue)]()
[![Authors](https://img.shields.io/badge/authors-489-green)]()

279,196 image alt-text pairs from 489 Bluesky accounts, collected via the public AT Protocol APIs. Every account was validated at 90%+ alt-text rate with substantive descriptions. One row per image, not per post.

## Overview

- **Collection period**: April 2026
- **Total rows**: 279,196
- **Unique authors**: 489
- **Mean alt text length**: 203 characters
- **Median**: 127 characters
- **60.5%** of entries exceed 100 characters
- **Languages**: English (85%), German (1.6%), French (0.8%), Portuguese (0.8%), 20+ others
- **Collection method**: AT Protocol `app.bsky.feed.getAuthorFeed` (public, no auth)

## Download

**GitHub Release** (recommended for bulk download):
- [`corpus.jsonl.gz`](https://github.com/data-poems/bluesky-alt-text/releases/latest) (89 MB)
- [`corpus.csv.gz`](https://github.com/data-poems/bluesky-alt-text/releases/latest) (77 MB)

## Quick start

```python
import pandas as pd

df = pd.read_json("corpus.jsonl.gz", lines=True)
print(f"{len(df):,} rows, {df['author_handle'].nunique()} authors")
df["alt_text"].str.len().describe()
```

See [`explore.ipynb`](https://github.com/data-poems/bluesky-alt-text/blob/main/explore.ipynb) for a walkthrough with visualizations.

## Schema

Each row is one image with alt text. A post with 4 images produces 4 rows.

| Field | Description |
|---|---|
| `alt_text` | The image description written by the author |
| `image_alt_length` | Character count |
| `text` | Post body text |
| `author_handle` | Bluesky handle (e.g. `tink.uk`) |
| `author_did` | Decentralized identifier |
| `post_uri` / `post_cid` | AT Protocol post identifiers |
| `created_at` / `indexed_at` | Timestamps (ISO 8601) |
| `langs_json` | Language tags as JSON array |
| `image_index` | Position of this image in the post (0-based) |
| `image_count_in_post` | Total images in the post |
| `image_mime_type` | MIME type |
| `image_thumb_url` / `image_fullsize_url` | CDN image URLs |
| `raw_record_json` | Complete AT Protocol record |

## Account selection

Not a random sample. 495 accounts found through eight strategies, then validated against the live API.

**Discovery strategies:**
1. [Alt Text Hall of Fame](https://bsky.app/profile/alttexthof.bsky.social) honorees and social graph
2. Accessibility keyword search ("alt text", "a11y", "WCAG", "screen reader")
3. Network tracing from 8 accessibility seed accounts
4. International search (German, French, Portuguese, Japanese, Spanish, Dutch, Swedish)
5. Institutional search (museums, zoos, aquariums, space agencies)
6. Photography and visual arts accounts
7. Jetstream firehose sampling for wild-caught writers

**Validation gate:**
- 90%+ of images have non-empty alt text
- Average alt text 50+ characters
- At least 10 images

Full account list: [`collector/actors.txt`](https://github.com/data-poems/bluesky-alt-text/blob/main/collector/actors.txt)

## Use cases

- Fine-tune vision-language models on quality human-written descriptions
- Benchmark generated alt text against real-world examples
- Study how people describe images for screen reader users
- Compare description styles across museums, photographers, scientists, advocates
- Pair with a firehose sample for contrastive training (good vs. minimal alt text)

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

[CC-BY 4.0](LICENSE). Use it for anything, just credit the source.

Collected from public Bluesky posts via documented AT Protocol APIs. No private data, no scraping, no authentication required.
