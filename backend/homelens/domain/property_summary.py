"""Catalog-grounded historical-sale summary with no generated claims."""

from __future__ import annotations

from homelens.domain.property import HistoricalSale


def historical_sale_summary(record: HistoricalSale) -> str:
    date = f"{record.sale_date:%B} {record.sale_date.day}, {record.sale_date.year}"
    return (
        f"This {record.property_type.lower()} at {record.address}, "
        f"{record.city}, {record.state} {record.zip} sold for "
        f"${record.sold_price_usd:,.0f} on {date}. "
        f"The sale record lists {record.beds:g} beds, {record.baths:g} baths, "
        f"{record.square_feet:,.0f} square feet, and year built {record.year_built}."
    )
