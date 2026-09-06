"""Declaration-versus-record reconciliation (Use Case 01 -- HB 127).

The statutory test in Sec. 51B.153 is a *failure to disclose a substantial
educational, employment, or research-related activity, publication, or
presentation*. That makes this a reconciliation problem: diff a declared
affiliation set against what public records show, and surface every
discrepancy as a Finding for an analyst to work.

- discover.py  -- adapters turning a discovery source (OpenAlex publications;
                  the GLEIF ownership chain, added in C3) into
                  DiscoveredAffiliation records.
- match.py     -- institution-name matching, tuned for two independently
                  authored names; reuses resolution/matcher.py's score_pair.
- reconcile.py -- the diff itself: DiscoveredAffiliation x Declaration ->
                  list[Finding], with the factual classification Section 4
                  permits and nothing it forbids.
"""
