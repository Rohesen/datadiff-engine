"""Generate the bookings example used in the README.

Two daily snapshots of an airline bookings table. The new snapshot has a
few realistic problems planted in it:

- the AE feed stopped sending the booking channel (null for every AE row),
  which barely moves the overall null rate;
- UK fares were loaded in the wrong currency (+40%), which only shows up
  clearly inside the UK segment;
- a new currency code appears;
- some bookings were cancelled (removed) and some fares were repriced.

Run:  python examples/make_bookings.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent


def make(seed: int = 7, n: int = 1500) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    country = rng.choice(["IN", "US", "UK", "AE"], n, p=[0.5, 0.25, 0.15, 0.10])
    currency = np.select(
        [country == "IN", country == "US", country == "UK"],
        ["INR", "USD", "GBP"],
        default="AED",
    )
    old = pd.DataFrame({
        "booking_id": np.arange(100_000, 100_000 + n),
        "country": country,
        "channel": rng.choice(["web", "app", "agent"], n, p=[0.5, 0.35, 0.15]),
        "currency": currency,
        "fare": rng.lognormal(mean=5.3, sigma=0.35, size=n).round(2),
        "booked_at": pd.Timestamp("2026-11-17")
        + pd.to_timedelta(np.sort(rng.integers(0, 86_400, n)), unit="s"),
    })

    new = old.copy()
    new.loc[new["country"] == "AE", "channel"] = None
    uk = new["country"] == "UK"
    new.loc[uk, "fare"] = (new.loc[uk, "fare"] * 1.4).round(2)
    repriced = new.sample(frac=0.03, random_state=seed).index
    new.loc[repriced, "fare"] = (new.loc[repriced, "fare"] * 1.05).round(2)
    new.loc[new.sample(frac=0.02, random_state=seed + 1).index, "currency"] = "EUR"
    new = new.drop(new.sample(frac=0.02, random_state=seed + 2).index)
    return old, new


if __name__ == "__main__":
    old, new = make()
    old.to_csv(HERE / "bookings_old.csv", index=False)
    new.to_csv(HERE / "bookings_new.csv", index=False)
    print(f"wrote {len(old)} and {len(new)} rows")
