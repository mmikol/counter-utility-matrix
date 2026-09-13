---
name: When patches shipped since capture, trust the kit
kind: strategy
category: uncertainty
---
# When patches shipped since capture, trust the kit

The board's first facts state when the rates were captured and warn
when patches have shipped since. Stale rates argue less: weight the
kit numbers, keywords and the authored playbook over win rates until
`pull_rates` runs again. The data layer makes that one tool call.
