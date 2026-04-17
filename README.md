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
  - es
  - ja
  - sq
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
  splits:
    - name: corpus
      num_examples: 279196
    - name: firehose
      num_examples: 125645
---

# Bluesky Alt Text: 279K Curated Image Descriptions

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightblue.svg)](https://creativecommons.org/licenses/by/4.0/)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Dataset-FFD21E)](https://huggingface.co/datasets/lukeslp/bluesky-alt-text)
[![GitHub](https://img.shields.io/badge/GitHub-Repo-181717)](https://github.com/data-poems/bluesky-alt-text)
[![Rows](https://img.shields.io/badge/rows-279,196-blue)]()
[![Authors](https://img.shields.io/badge/authors-489-green)]()

279,196 image alt-text pairs from 489 Bluesky accounts, collected via the public AT Protocol APIs. Every account validated at 90%+ alt-text rate with substantive descriptions. One row per image, not per post.

Includes a 125K-row firehose sample (14.5 hours of live network traffic) for contrastive analysis.

## Overview

- **Collection period**: April 2026
- **Total rows**: 279,196 (corpus) + 125,645 (firehose) = 404,841
- **Unique authors**: 489 (corpus), 34,785 (firehose)
- **Mean alt text length**: 203 characters
- **Median**: 127 characters
- **60.5%** of entries exceed 100 characters
- **Languages**: English (94%), German, French, Portuguese, Spanish, Japanese, 20+ others
- **Collection method**: AT Protocol `getAuthorFeed` (corpus), Jetstream WebSocket (firehose)

## Download

**GitHub Release** (recommended for bulk download):
- [`corpus.jsonl.gz`](https://github.com/data-poems/bluesky-alt-text/releases/latest) (89 MB)
- [`corpus.csv.gz`](https://github.com/data-poems/bluesky-alt-text/releases/latest) (77 MB)
- [`firehose.jsonl.gz`](https://github.com/data-poems/bluesky-alt-text/releases/latest) (49 MB)

## Quick Start

```python
import pandas as pd

corpus = pd.read_json("corpus.jsonl.gz", lines=True)
firehose = pd.read_json("firehose.jsonl.gz", lines=True)

print(f"Corpus: {len(corpus):,} rows, mean alt {corpus.alt_text.str.len().mean():.0f} chars")
print(f"Firehose: {len(firehose):,} rows, mean alt {firehose.alt_text.str.len().mean():.0f} chars")
```

See [`explore.ipynb`](https://github.com/data-poems/bluesky-alt-text/blob/main/explore.ipynb) for a walkthrough with visualizations.

## Two Datasets

The targeted corpus and firehose sample are separate files with the same schema. Use them together or independently.

| | Targeted corpus | Firehose sample |
|---|---|---|
| **File** | `corpus.jsonl.gz` | `firehose.jsonl.gz` |
| **Rows** | 279,196 | 125,645 |
| **Source** | `getAuthorFeed` from 495 validated accounts | Jetstream live stream (14.5-hour window) |
| **Alt text quality** | High (accounts verified at 90%+ rate) | Mixed (reflects platform-wide behavior) |
| **Use case** | Training, benchmarking, style analysis | Adoption rates, contrastive training |
| **Reproducibility** | Deterministic from account list | Time-dependent snapshot |

## Schema

Each row is one image with alt text. A post with 4 images produces 4 rows.

| Field | Type | Description |
|---|---|---|
| `alt_text` | string | Image description written by the author |
| `image_alt_length` | int | Character count of the alt text |
| `text` | string | Post body text |
| `author_handle` | string | Bluesky handle (e.g. `tink.uk`) |
| `author_did` | string | Decentralized identifier |
| `post_uri` | string | AT Protocol post URI |
| `post_cid` | string | Content identifier (hash) |
| `created_at` | string | Post creation time (ISO 8601) |
| `indexed_at` | string | Index time (ISO 8601) |
| `langs_json` | string | Language tags as JSON array |
| `image_index` | int | Position of this image in the post (0-based) |
| `image_count_in_post` | int | Total images in the post |
| `image_mime_type` | string | MIME type of the image blob |
| `image_ref` | string | AT Protocol blob reference |
| `image_thumb_url` | string | CDN thumbnail URL (AppView only) |
| `image_fullsize_url` | string | CDN full-size URL (AppView only) |
| `source_mode` | string | Collection mode (`author_feed` or `jetstream`) |
| `collected_at` | string | When this row was collected (ISO 8601) |
| `query` | string | Actor handle or search query used |
| `cursor` | string | Pagination cursor at collection time |
| `raw_record_json` | string | Complete AT Protocol record as JSON |

## Account Selection

Not a random sample. 495 accounts found through eight strategies, then validated against the live API.

**Discovery:**
1. [Alt Text Hall of Fame](https://bsky.app/profile/alttexthof.bsky.social) honorees and social graph
2. Accessibility keyword search ("alt text", "a11y", "WCAG", "screen reader")
3. Network tracing from 8 accessibility seed accounts
4. International search (German, French, Portuguese, Japanese, Spanish, Dutch, Swedish)
5. Institutional search (museums, zoos, aquariums, space agencies)
6. Photography and visual arts accounts
7. Jetstream firehose sampling for wild-caught writers

**Validation gate** (every account probed against the live API):
- 90%+ of images have non-empty alt text
- Average alt text 50+ characters
- At least 10 images in sample

Full account list: [`collector/actors.txt`](https://github.com/data-poems/bluesky-alt-text/blob/main/collector/actors.txt)

## Known Quirks

- **Firehose has no `image_thumb_url` or `image_fullsize_url`**. Jetstream delivers raw commit records without CDN URLs. These fields are null for firehose rows.
- **`langs_json` is author-declared**, not detected. Some posts have empty language tags.
- **`raw_record_json` can be large**. Multi-image posts with long text produce records >10 KB. If you don't need provenance auditing, drop this column.
- **Quote-posts included**. Posts with `app.bsky.embed.recordWithMedia` (image + quote) are collected alongside standard image posts.

## Use Cases

- Fine-tune vision-language models on quality human-written descriptions
- Benchmark generated alt text against real-world examples
- Study how people describe images for screen reader users
- Compare description styles across museums, photographers, scientists, advocates
- Contrastive training: pair corpus (high quality) with firehose (mixed quality)

## Distribution

- **GitHub**: [data-poems/bluesky-alt-text](https://github.com/data-poems/bluesky-alt-text)
- **HuggingFace**: [lukeslp/bluesky-alt-text](https://huggingface.co/datasets/lukeslp/bluesky-alt-text)

## Citation

```bibtex
@dataset{steuber2026blueskyalttext,
  title     = {Bluesky Alt Text Dataset},
  author    = {Steuber, Luke},
  year      = {2026},
  publisher = {GitHub / HuggingFace},
  url       = {https://github.com/data-poems/bluesky-alt-text},
  license   = {CC-BY-4.0},
  note      = {279,196 image alt-text pairs from 489 validated Bluesky accounts}
}
```

## Structured Data (JSON-LD)

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "Bluesky Alt Text Dataset",
  "description": "279,196 image alt-text pairs from 489 validated Bluesky accounts, collected via AT Protocol APIs.",
  "url": "https://github.com/data-poems/bluesky-alt-text",
  "sameAs": [
    "https://huggingface.co/datasets/lukeslp/bluesky-alt-text"
  ],
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "creator": {
    "@type": "Person",
    "name": "Luke Steuber",
    "url": "https://lukesteuber.com"
  },
  "keywords": ["alt text", "accessibility", "image description", "bluesky", "at protocol", "a11y", "screen reader"],
  "temporalCoverage": "2023/2026",
  "distribution": [
    {
      "@type": "DataDownload",
      "encodingFormat": "application/x-ndjson",
      "contentUrl": "https://github.com/data-poems/bluesky-alt-text/releases/latest"
    }
  ]
}
```

## Bluesky Ecosystem

More Bluesky tools by Luke Steuber:

- [bsky-firehose-anonymized-dec-2025](https://github.com/data-poems/bsky-firehose-anonymized-dec-2025) -- 101K anonymized firehose posts
- [bluedrop](https://github.com/lukeslp/bluedrop) -- browser extension for DMs, Zen Mode, and dark mode
- [skymarshal](https://github.com/lukeslp/skymarshal) -- Python CLI for post and comment management
- [skymarshal-js](https://github.com/lukeslp/skymarshal-js) -- TypeScript/JS toolkit for AT Protocol

## License

[CC-BY 4.0](LICENSE). Use it for anything, just credit the source.

Collected from public Bluesky posts via documented AT Protocol APIs. No private data, no scraping, no authentication required.

## Author

**Luke Steuber**
- Website: [lukesteuber.com](https://lukesteuber.com)
- Bluesky: [@lukesteuber.com](https://bsky.app/profile/lukesteuber.com)
- Contact: luke@lukesteuber.com
