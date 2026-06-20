"""4 Ducks methodology knowledge — injected into the system prompt when active."""

FOUR_DUCKS_KNOWLEDGE = """\
## FunnelFighters — 4 Ducks Marketing Intelligence

### The 4 Ducks

**Principle:** All 4 ducks must be in a row. When Audience, Ad, Landing Page, \
and Product share the same expectation, people convert. When even one is off, \
the funnel leaks.

```
AUDIENCE  →  AD  →  LANDING PAGE  →  PRODUCT
Who sees     What they   Where they       What they
it           see         land             experience

Intent       Expectation Continue that    Deliver that
                         expectation      value
```

| Duck | Role | Alignment criterion |
|------|------|---------------------|
| **Audience** | Who sees the ad | Real intent; isolated segment; not "everyone" |
| **Ad** | What they see | Shows the product; sets honest expectation matching intent |
| **Landing Page** | Where they land | Dedicated per campaign; continues ad expectation; one message + product visible |
| **Product** | What they experience | Delivers on promise; gets people to **pay** |

**Intent is the thread** connecting all four. Each LP has a `value_prop`; \
signups inherit that intent. If the ad promises "AI meeting summaries" but \
the LP talks "project management" → bounce spikes. That's a broken duck.

### tROI — The North Star

**tROI = days from when a dollar is spent on an ad to when that dollar has \
been fully returned through customer payments.**

| Range | Meaning | Action |
|-------|---------|--------|
| <30 days | Healthy — scale up | Increase budget |
| 30–90 days | Acceptable for high-LTV | Monitor |
| >90 days or ∞ | Burning cash | Kill or pause |

Calculated per campaign, ad, audience, LP, country, and week.

### Two Number Systems

| System | Knows | Doesn't know |
|--------|-------|--------------|
| **Google Ads** | Impressions, clicks, cost, Google conversions | Activation, payment, LTV, churn |
| **Product tracking** | Signups → milestones → revenue per user | Which campaign spent to acquire them |

FunnelFighters bridges both via gclid/UTM attribution.

### Scoring

Each duck scored 0–100. **Alignment score** = minimum of 5 cross-duck criteria:
1. Audience → Ad message match (20%)
2. Ad → LP expectation continuity (25%)
3. LP → Product promise delivery (25%)
4. End-to-end intent thread (15%)
5. Visual/design consistency (15%)

### Two Speeds

- **Hourly tactical:** pause bleeding ads, shift bids, add negative keywords
- **Weekly strategic:** kill campaigns, redesign LPs, restructure

### Key Vocabulary

Cohorts, Signups, Activated, Paying, Upgraded, Revenue, tROI, 4 Ducks, \
Alignment, Value Prop, ICP (Ideal Customer Profile), Intent, Expectation, \
Funnel Waterfall, Portfolio ROAS, CPA, LTV, Impression Share.

### When to use FunnelFighters tools

- Owner asks about marketing performance → ff_portfolio_summary first, then drill down
- Owner asks about a specific campaign → ff_campaign_detail
- Owner asks "where is the funnel leaking" → ff_funnel + ff_duck_reports
- Owner asks about ROI/spend → ff_roi_summary + ff_wasted_spend
- Owner asks "are my ads working" → ff_ads + ff_keywords
- Owner asks about landing pages → ff_landing_pages + ff_duck_analyze
- Owner says "run 4 ducks" → ff_duck_analyze
- For any date-range query, default to 28 days if not specified
"""
