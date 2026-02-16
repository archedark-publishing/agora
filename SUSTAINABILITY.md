# Agora Sustainability Plan

How we keep Agora running without going broke.

---

## Cost Model

### Infrastructure Costs

| Component | Provider | Cost | Notes |
|-----------|----------|------|-------|
| VM | exe.dev | ~$10/mo | Small instance sufficient for MVP |
| Database | PostgreSQL on VM | $0 | Included in VM |
| CDN | Cloudflare | $0 | Free tier handles significant traffic |
| Domain | TBD | ~$15/yr | One-time annual cost |
| SSL | Cloudflare | $0 | Free with CF |

**Baseline cost: ~$10-15/month**

### Scaling Costs

| Scale | Agents | Requests/day | Est. Cost | Notes |
|-------|--------|--------------|-----------|-------|
| MVP | 10-100 | 1K | $10/mo | Current VM |
| Growth | 1K | 100K | $10/mo | Still fine with caching |
| Popular | 10K | 1M | $20-50/mo | May need bigger VM |
| Viral | 100K | 10M+ | $100+/mo | Need mitigation strategies |

---

## Cost Drivers

### 1. API Requests (Primary Risk)
- Every query = compute + bandwidth
- Uncached: ~1KB response × millions = real money
- **Mitigation:** Aggressive caching, static export

### 2. Health Checks (Secondary Risk)
- N agents × checks/hour = N outbound requests
- 100K agents × 1/hour = 100K requests/hour
- **Mitigation:** Hourly checks, only check recently-queried agents

### 3. Database (Low Risk)
- Agents are small (~2KB each)
- 100K agents = ~200MB
- Postgres handles this trivially

### 4. Bandwidth (Medium Risk)
- Static export: ~2KB/agent × 100K = 200MB file
- If downloaded 1000x/hour = 200GB/hour
- **Mitigation:** CDN caching, compression

---

## Mitigation Strategies

### Layer 1: Caching (Always On)

**Cloudflare in front of everything:**
- Cache all GET requests (5 min TTL)
- Cache `/registry.json` (1 hour TTL)
- Serves from edge, never hits origin
- Free tier: 100K requests/day minimum

**Result:** 90%+ of reads never hit our server.

### Layer 2: Rate Limiting (Always On)

**Aggressive limits push consumers to better patterns:**

| User Type | Limit | Guidance |
|-----------|-------|----------|
| Anonymous | 100 req/hour | Use /registry.json |
| API Key | 1000 req/hour | Cache locally |
| Abusive | Blocked | Contact us |

**Result:** No single consumer can bankrupt us.

### Layer 3: Static Export (Always On)

**`/registry.json` updated hourly:**
- Full agent dump
- Consumers download once, search locally
- Cached at CDN edge
- Most bulk use cases served this way

**Result:** Heavy consumers don't need real-time API.

### Layer 4: Health Check Throttling (Adaptive)

**Smart health checking:**
- Default: 1 hour interval (not 5 min)
- Only check agents queried in last 24h
- Inactive agents stay "unknown" until searched
- Can disable entirely if costs spike

**Result:** Outbound requests scale with actual usage, not total agents.

### Layer 5: Budget Cap (Emergency)

**Hard monthly limit (configurable, e.g., $50):**

When budget exhausted:
1. Disable health checks
2. Disable new registrations
3. Serve only cached data
4. Alert maintainers
5. Wait for next billing cycle

**Result:** Costs cannot exceed cap, ever.

### Layer 6: Degraded Mode (Emergency)

If infrastructure is overwhelmed:
1. Return cached `/registry.json` for all queries
2. Disable dynamic search
3. Show "high load" banner on web UI
4. Queue writes for later processing

**Result:** Service stays up, just slower.

---

## Revenue Options (If Needed)

### Tier 1: Community Support
- GitHub Sponsors
- Open Collective
- "Powered by community" badge

### Tier 2: Sponsorship
- "Sponsored by X" on homepage
- Logo in README
- No influence over content/rankings

### Tier 3: Premium API
- Higher rate limits
- Priority health checks
- Webhook notifications
- SLA guarantee
- **Price:** $10-50/month

### Tier 4: Enterprise Self-Host
- Support contract for running own instance
- Federation setup assistance
- **Price:** Consulting rates

---

## Federation Escape Hatch

If Agora becomes critical infrastructure:

1. **Publish reference implementation** (already open source)
2. **Document self-hosting** (already in spec)
3. **Federation protocol** (future)
4. **Let others run instances**

We become one node in a network, not the only node. Decentralize the load and responsibility.

---

## Monitoring & Alerts

### Metrics to Track
- Requests/hour (by endpoint)
- Cache hit rate
- Database size
- Health check queue depth
- Error rate
- Estimated monthly cost

### Alert Thresholds
| Metric | Warning | Critical |
|--------|---------|----------|
| Monthly cost | 50% of budget | 80% of budget |
| Cache hit rate | <80% | <50% |
| Error rate | >1% | >5% |
| Response time | >500ms | >2s |

### Response Playbook
1. **High cost:** Enable more aggressive rate limits
2. **Low cache hit:** Check CF config, extend TTLs
3. **High errors:** Check health check failures
4. **Slow responses:** Check database, consider index

---

## Commitment

We commit to:
1. **Transparency:** Public cost reporting if we take donations
2. **No ads:** Never selling user data or showing ads
3. **Open source:** Always MIT licensed
4. **Graceful shutdown:** 30 days notice if we can't continue

---

## Summary

| Scenario | Monthly Cost | Risk Level |
|----------|--------------|------------|
| Normal operation | $10-15 | ✅ Low |
| Moderate success | $20-50 | ✅ Low |
| Popular | $50-100 | ⚠️ Medium |
| Viral | $100+ | 🚨 High (mitigations kick in) |

**Bottom line:** With proper caching and rate limiting, we can handle significant scale on minimal budget. If we outgrow that, we have escape hatches (sponsorship, premium tier, federation) before costs become untenable.

---

*This document should be updated as we learn actual usage patterns.*
