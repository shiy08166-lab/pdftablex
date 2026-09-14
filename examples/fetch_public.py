"""Download a small, public-domain dataset to test against.

Real data is a better test than invented data: it has long values that wrap
awkwardly, quoted fields containing commas, mixed numeric precision, and text
with actual English words in it — which is what the dictionary-guided repairs
need in order to be exercised at all.

    python examples/fetch_public.py            # download (skips if cached)
    python examples/fetch_public.py --force    # re-download

The data lands in ``examples/public/``, which is **git-ignored**: this
repository ships code, not data. Provenance is written to
``examples/public/SOURCE.md`` next to the file.

Source: <https://ourairports.com/data/> — OurAirports, released into the public
domain by its maintainers.
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
FILENAME = "airports.csv"

SOURCE_MD = """# Data provenance

**File:** `{filename}`
**Source:** OurAirports — <https://ourairports.com/data/>
**URL:** {url}
**Retrieved by:** `examples/fetch_public.py`
**Licence:** Public domain. The OurAirports maintainers state that the data is
released into the public domain; no attribution is legally required, and the
credit is given here anyway.

19 columns, ~86,000 rows. Three of the columns (``name``, ``municipality``,
``keywords``) hold prose-like text, which is what makes this dataset useful for
exercising the dictionary-guided repairs.

This directory is git-ignored. The repository ships code, not data.
"""


def fetch(outdir: Path, force: bool = False) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / FILENAME
    if target.exists() and not force:
        print(f"cached: {target} ({target.stat().st_size:,} bytes)")
        return target

    print(f"downloading {URL}")
    with urllib.request.urlopen(URL, timeout=180) as response:
        payload = response.read()
    if b"latitude_deg" not in payload[:400]:
        raise RuntimeError(
            "unexpected response — the dataset may have moved or returned an error page"
        )
    target.write_bytes(payload)

    (outdir / "SOURCE.md").write_text(
        SOURCE_MD.format(filename=FILENAME, url=URL), encoding="utf-8"
    )
    print(f"wrote {target} ({len(payload):,} bytes)")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=str(Path(__file__).resolve().parent / "public"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    fetch(Path(args.outdir), args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
