# Fleet Onboarding Intake — Project Questionnaire

Complete all sections. Unanswered questions = automatic hold.
Send completed form back to the fleet operator.

---

## Section 1: Project Identity

1. **Server name** (slug, lowercase-hyphenated): `property-descriptions-mcp`
2. **Proposed PyPI package name**: `property-descriptions-mcp`
3. **Proposed Fly.io app name**: `bouch-property-descriptions-mcp`
4. **GitHub repo** (full URL): https://github.com/paulieb89/property-descriptions-mcp
5. **One-line description** (for README + Smithery listing): Generate UK property listing descriptions with real market data
6. **What user problem does this solve?** (2–3 sentences): Writing listing copy is time-consuming and AI without real data hallucinates prices and features. This server grounds Claude in live Land Registry comps, EPC ratings, and Rightmove listings so descriptions are fast to generate and factually accurate.

---

## Section 2: Technical Readiness

7. **Framework**: Is this FastMCP? [x] Yes  [ ] No (explain): ___
8. **Python version**: minimum required: 3.11
9. **Runtime dependencies** (list all from `pyproject.toml [project.dependencies]`): fastmcp>=3.2.4, property-shared>=1.6.1, httpx, uvicorn[standard]
10. **Does the server require any API keys or secrets?**
    - [ ] No — fully open data
    - [x] Yes — list each key and the external service it authenticates: `EPC_API_EMAIL` + `EPC_API_KEY` for the EPC Register API (both optional — server degrades gracefully without them)
11. **Does it expose a `/health` endpoint returning `{"status": "healthy"}`?** [ ] Yes  [x] No — currently returns `{"status": "ok"}` — needs fix
12. **Does it expose `/.well-known/mcp/server-card.json`?** [ ] Yes  [x] No — not yet implemented
13. **Does it expose `/.well-known/glama.json` with `paul@bouch.dev` as maintainer?** [ ] Yes  [x] No — not yet implemented
14. **Does `fly.toml` follow the standard pattern** (port 8080, `auto_stop_machines = "off"`, health check on `/health`, `[metrics]` block)?
    - [ ] Yes  [x] No — port 8080 ✅, auto_stop_machines="off" ✅, health check /health ✅, but `[metrics]` block is missing
15. **Estimated memory footprint** (which `[[vm]]` memory tier fits — 256mb / 512mb / 1gb / 2gb?): 256mb
16. **Does it have a `/metrics` endpoint in Prometheus text format?** [ ] Yes  [x] No  [ ] Planned

---

## Section 3: Data & Scope

17. **What external data sources or APIs does it call?**
    - Land Registry Price Paid Data — via property-shared — open
    - EPC Register API — via property-shared — API key (optional)
    - Postcode lookup — via property-shared — open
    - Rightmove API — via property-shared — open
    - Rightmove image CDN — direct httpx fetch — open
18. **Rate limits or quotas** on those APIs — what happens when they're hit?
    Configurable per-service timeouts (PPD 4s, EPC 4s, postcode 3s, Rightmove 4s, images 5s). On failure, errors are surfaced in the `errors` dict in the tool response — the server does not crash.
19. **Estimated token size of typical tool responses** — small (<2k), medium (2–10k), large (>10k)?
    - `get_property_data`: medium (2–10k)
    - `get_listing_detail`: large (>10k — includes images as binary content)
    - `format_for_portals`: small (<2k)
20. **Does any tool return binary data, file downloads, or streaming responses?** [x] Yes  [ ] No
    If yes, describe handling: `get_listing_detail` fetches property photos from Rightmove CDN via httpx and returns them as `Image` content blocks (jpeg/png) embedded in the tool result.
21. **Is any returned data personally identifiable (PII) or legally sensitive?** [x] Yes  [ ] No
    If yes, describe what and how it's handled: Property addresses, sale prices, EPC ratings, and agent contact info are returned. This is appropriate for the intended estate-agent audience. Data passes through from official public registers (Land Registry, EPC Register) without additional filtering or redaction.

---

## Section 4: CI/CD & Release Readiness

22. **Does `.github/workflows/release.yml` exist with `on: release: types: [published]`?**
    [x] Yes  [ ] No  [ ] Not yet written
23. **Two-job pipeline (publish PyPI → deploy Fly)?** [ ] Yes  [ ] No  [x] PyPI not needed
24. **Is PyPI Trusted Publisher configured** (pending publisher on pypi.org + `pypi` GitHub environment)?
    [ ] Yes  [ ] No  [x] Not publishing to PyPI
25. **Has the Fly.io app been created (`fly apps create <name>`)?** [x] Yes  [ ] No
26. **Is there a per-app `FLY_API_TOKEN` secret set on the GitHub repo?** [x] Yes  [ ] No
27. **Has a first deploy succeeded (`fly deploy --ha=false`)?** [x] Yes  [ ] No
28. **Verify all three endpoints post-deploy** (paste actual curl responses):
    - `/health`: `{"status":"ok"}` — ⚠️ needs updating to `{"status":"healthy"}`
    - `/.well-known/glama.json`: 404 — endpoint not yet implemented
    - `/.well-known/mcp/server-card.json`: 404 — endpoint not yet implemented

---

## Section 5: Documentation & Listing

29. **Does the repo have a `README.md` with:**
    - `<!-- mcp-name: io.github.paulieb89/<repo-name> -->` comment? [ ] Yes  [x] No — missing
    - Installation instructions (uvx + Fly URL)? [x] Yes  [ ] No
    - Tool documentation (each tool named and described)? [x] Yes  [ ] No
30. **Does the repo have an `AGENTS.md`** (prompt template for Claude/agents using this server)?
    [ ] Yes  [x] No — not yet written
31. **Has the server been submitted to Glama** (glama.ai → Servers → Add)?
    [ ] Yes  [ ] No  [x] Will do post-accept
32. **Has the server been submitted to Smithery?**
    [ ] Yes  [ ] No  [x] Will do post-accept
33. **Is there a planned bouch.dev product page** at `/products/<name>-mcp/`?
    [x] Yes  [ ] No — planned at `/products/property-descriptions-mcp/`, not yet written

---

## Section 6: Maintenance Commitment

34. **Who is the primary maintainer?** Paul Boucherat (paulboucherat@gmail.com)
35. **What is the expected update frequency?** (weekly / monthly / as-needed): monthly
36. **Are there known breaking changes coming** in the external APIs this wraps? [ ] Yes  [x] No
37. **Is there an existing test suite?** [ ] Yes  [x] No
    If yes, command to run: ___
38. **Any known issues, instabilities, or TODOs that would affect production?** Fleet audit needed against MCP lessons and FastMCP canonical examples before final production sign-off.
