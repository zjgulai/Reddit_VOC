from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
CATALOG_URL = "https://momcozy.com/collections/all/products.json?limit=250&page={page}"
AGENT_INSTRUCTIONS_URL = "https://momcozy.com/agents.md"


PRODUCT_FAMILIES = [
    {
        "family_id": "m5-smart",
        "handle": "m5-smart-wearable-breast-pump-upgraded-with-app-control",
        "dictionary_runtime_aliases": ["M5"],
        "internal_spu_ids": ["SPU001001001003016"],
        "candidate_search_terms": ['"Momcozy M5 Smart"'],
    },
    {
        "family_id": "m6-mobile-style",
        "handle": "momcozy-mobile-style-hands-free-breast-pump",
        "dictionary_runtime_aliases": ["M6"],
        "internal_spu_ids": [],
        "candidate_search_terms": ['"Momcozy Mobile Style"'],
    },
    {
        "family_id": "m9-mobile-flow",
        "handle": "momcozy-mobile-flow-hands-free-breast-pump",
        "dictionary_runtime_aliases": ["M9", "Mobile Flow"],
        "internal_spu_ids": ["SPU000168"],
        "candidate_search_terms": [],
    },
    {
        "family_id": "s9-pro",
        "handle": "momcozy-s9-pro-wearable-breast-pump",
        "dictionary_runtime_aliases": ["S9", "S9 Pro"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "s12-pro-quick",
        "handle": "s12-pro-quick-wearable-breast-pump",
        "dictionary_runtime_aliases": ["S12", "S12 Pro"],
        "internal_spu_ids": [],
        "candidate_search_terms": ['"Momcozy S12 Pro Quick"'],
    },
    {
        "family_id": "v1-pro",
        "handle": "v1-pro-hospital-grade-wearable-breast-pump",
        "dictionary_runtime_aliases": ["V1", "V1 Pro"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "v2-pro",
        "handle": "v2pro-hands-free-breast-pump-ultra-light-potent",
        "dictionary_runtime_aliases": ["V2", "V2 Pro"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "air-1",
        "handle": "momcozy-air-1-ultra-slim-breast-pump",
        "dictionary_runtime_aliases": ["Air 1"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "wellness-1-w1",
        "handle": "momcozy-wellness-1-warm-massage-wearable-breast-pump-w1",
        "dictionary_runtime_aliases": ["W1"],
        "internal_spu_ids": [],
        "candidate_search_terms": ['"Momcozy Wellness 1"'],
    },
    {
        "family_id": "kleanpal-pro",
        "handle": "momcozy-kleanpal-pro-baby-bottle-washer",
        "dictionary_runtime_aliases": ["KleanPal", "KleanPal Pro"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "deepclean-d8",
        "handle": "momcozy-deepclean-baby-bottle-washer-d8",
        "dictionary_runtime_aliases": ["D8"],
        "internal_spu_ids": [],
        "candidate_search_terms": ['"Momcozy DeepClean"'],
    },
    {
        "family_id": "dinerpal",
        "handle": "momcozy-dinerpal-high-chair",
        "dictionary_runtime_aliases": ["DinerPal"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "purehug",
        "handle": "ergonomic-cozy-and-lightweight-baby-carrier",
        "dictionary_runtime_aliases": ["PureHug"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "weesnug",
        "handle": "momcozy-weesnug-newborn-carrier",
        "dictionary_runtime_aliases": ["WeeSnug"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "bumpease-ergonest",
        "handle": "momcozy-bellyembrace-maternity-belly-band",
        "dictionary_runtime_aliases": ["BumpEase", "Ergonest"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "dreamlign",
        "handle": "momcozy-pregnancy-pillow-for-sleeping",
        "dictionary_runtime_aliases": ["Dreamlign"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "ergowrap",
        "handle": "momcozy-ergowrap-postpartum-belly-band",
        "dictionary_runtime_aliases": ["Ergowrap"],
        "internal_spu_ids": [],
        "candidate_search_terms": [],
    },
    {
        "family_id": "bm03-video-monitor",
        "handle": "momcozy-5-5-full-hd-video-baby-monitor-bm03",
        "dictionary_runtime_aliases": ["BM03"],
        "internal_spu_ids": [],
        "candidate_search_terms": ['"Momcozy BM03"'],
    },
]


def fetch_page(page: int) -> tuple[bytes, dict[str, object]]:
    url = CATALOG_URL.format(page=page)
    request = Request(url, headers={"User-Agent": "Reddit-VOC-catalog-audit/1.0"})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    return raw, json.loads(raw)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    fetched_at = datetime.now(timezone.utc).isoformat()
    raw_pages: list[bytes] = []
    products: list[dict[str, object]] = []
    page_counts: list[int] = []
    for page in (1, 2, 3):
        raw, payload = fetch_page(page)
        raw_pages.append(raw)
        page_products = payload.get("products")
        if not isinstance(page_products, list):
            raise RuntimeError(f"catalog page {page} has no products list")
        page_counts.append(len(page_products))
        products.extend(page_products)
        if len(page_products) < 250:
            break

    handles = [str(product["handle"]) for product in products]
    ids = [int(product["id"]) for product in products]
    by_handle = {str(product["handle"]): product for product in products}
    expected_handles = {str(row["handle"]) for row in PRODUCT_FAMILIES}
    missing_handles = sorted(expected_handles - set(by_handle))
    if missing_handles:
        raise RuntimeError(f"official catalog handles missing: {missing_handles}")

    canonical_products = []
    for family in PRODUCT_FAMILIES:
        product = by_handle[str(family["handle"])]
        canonical_products.append(
            {
                "family_id": family["family_id"],
                "official_catalog_product_id": product["id"],
                "official_title": product["title"],
                "official_handle": product["handle"],
                "official_url": f"https://momcozy.com/products/{product['handle']}",
                "product_type": product.get("product_type", ""),
                "published_at": product.get("published_at"),
                "updated_at": product.get("updated_at"),
                "dictionary_runtime_aliases": family["dictionary_runtime_aliases"],
                "internal_spu_ids": family["internal_spu_ids"],
                "internal_mapping_status": (
                    "dictionary_alias_supported"
                    if family["internal_spu_ids"]
                    else "official_title_only_no_internal_spu_join"
                ),
                "candidate_search_terms": family["candidate_search_terms"],
            }
        )

    verified_existing_aliases = sorted(
        {
            alias
            for product in canonical_products
            if product["family_id"] != "bm03-video-monitor"
            for alias in product["dictionary_runtime_aliases"]
        },
        key=str.casefold,
    )
    candidate_terms = [
        term
        for product in canonical_products
        for term in product["candidate_search_terms"]
    ]
    checks = {
        "catalog_pages_terminate": page_counts[-1] < 250,
        "catalog_products_nonzero": len(products) > 0,
        "catalog_product_ids_unique": len(ids) == len(set(ids)),
        "catalog_handles_unique": len(handles) == len(set(handles)),
        "canonical_families_18": len(canonical_products) == 18,
        "existing_aliases_verified_24": len(verified_existing_aliases) == 24,
        "official_candidate_terms_6": len(candidate_terms) == 6,
        "bs03_not_equated_to_bm03": all(
            "BS03" not in product["dictionary_runtime_aliases"]
            for product in canonical_products
        ),
    }
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    snapshot = {
        "schema_version": "momcozy_official_product_catalog_snapshot_v1",
        "captured_at_utc": fetched_at,
        "source": {
            "authority": "Momcozy official Shopify storefront",
            "agent_instructions_url": AGENT_INSTRUCTIONS_URL,
            "catalog_urls": [CATALOG_URL.format(page=page) for page in range(1, len(page_counts) + 1)],
            "page_counts": page_counts,
            "page_sha256": [sha256(raw).hexdigest() for raw in raw_pages],
            "catalog_product_count": len(products),
        },
        "checks": checks,
        "canonical_product_families": canonical_products,
        "verified_existing_aliases": verified_existing_aliases,
        "official_catalog_candidate_terms": candidate_terms,
        "unresolved_internal_aliases": [
            {
                "alias": "BS03",
                "internal_spu_id": "SPU000714",
                "reason": "No exact BS03 title or handle exists in the current official catalog; BM03 is a different model string and is not treated as equivalent.",
            }
        ],
        "boundary": {
            "official_catalog_product_id_is_not_internal_spu_id": True,
            "full_internal_spu_join_complete": False,
            "safe_use": "Search-alias enrichment and official product-name evidence only.",
            "forbidden_use": "Do not infer a complete spu_id-to-product-title mapping.",
            "provider_call": False,
            "production_unchanged": True,
            "live_send": False,
        },
    }
    json_path = OUT / "official-product-catalog-snapshot.json"
    csv_path = OUT / "official-product-name-catalog.csv"
    write_json(json_path, snapshot)

    csv_rows = []
    for product in canonical_products:
        csv_rows.append(
            {
                "family_id": product["family_id"],
                "official_title": product["official_title"],
                "official_catalog_product_id": product["official_catalog_product_id"],
                "product_type": product["product_type"],
                "official_url": product["official_url"],
                "dictionary_runtime_aliases": " | ".join(product["dictionary_runtime_aliases"]),
                "internal_spu_ids": " | ".join(product["internal_spu_ids"]),
                "internal_mapping_status": product["internal_mapping_status"],
                "candidate_search_terms": " | ".join(product["candidate_search_terms"]),
                "published_at": product["published_at"],
                "updated_at": product["updated_at"],
            }
        )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(csv_rows)

    print(
        json.dumps(
            {
                "catalog_products": len(products),
                "canonical_families": len(canonical_products),
                "verified_existing_aliases": len(verified_existing_aliases),
                "official_candidate_terms": len(candidate_terms),
                "json_sha256": sha256(json_path.read_bytes()).hexdigest(),
                "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
