# Amaura Ventures — Governed Revenue Engine

Amaura Ventures is a separate internal startup studio. Its mandate is to generate product revenue that funds Amaura Labs' research, subscriptions, APIs, cloud GPUs, experiments and future hardware. It is not a public agency and does not accept arbitrary custom work.

## Non-negotiable doctrine

- Amaura Labs remains the long-term AI research and product company.
- Ventures builds owned products: mobile apps, micro-SaaS, web apps, extensions, developer tools, templates, games and focused AI utilities.
- Evidence comes before code.
- Every product has one target user, one painful problem, one primary channel and one primary metric.
- A validation sprint may not exceed fourteen days.
- One active sprint is allowed by default; one active build or launch is enforced.
- The founder attention budget defaults to twenty minutes per decision.
- Agents may research, score, draft, build in a sandbox, test, measure and recommend.
- Founder approval is mandatory before validation investment, external demand tests, launch, pricing, spending, scaling, shutdown or strategic commitment.
- Weak products are killed quickly. Sunk cost is not evidence.

## Deterministic opportunity score

| Dimension | Weight |
|---|---:|
| Pain severity | 25% |
| Evidence quality | 20% |
| Distribution fit | 20% |
| Speed to test | 15% |
| Monetisation | 10% |
| Strategic fit | 10% |

The default qualification threshold is 70/100. It can be changed with `AMAURA_VENTURE_MIN_SCORE`, but lowering it is not recommended.

## Workflow

1. Opportunity Researcher gathers direct public evidence.
2. Validation Analyst scores the idea and defines a falsifiable experiment.
3. Ventures Director selects at most one candidate.
4. Founder approves the exact fourteen-day sprint.
5. Distribution Operator prepares an honest pre-build demand test.
6. Founder approves the exact public test.
7. Existing product and engineering agents build only the smallest approved MVP.
8. QA and Security independently verify it.
9. Founder approves launch, pricing draft and rollback.
10. Portfolio Analyst records sourced activation, retention, revenue, cost and founder-time metrics.
11. The system recommends continue, kill, iterate or double down.
12. Founder makes the portfolio decision.

## CLI

```bash
amaura ventures status
amaura ventures opportunities --status qualified
amaura ventures opportunity-add --help
amaura ventures start <opportunity_id> --help
amaura ventures metric <experiment_id> --help
amaura ventures recommend <experiment_id>
amaura ventures decide <experiment_id> --decision kill --reason "Threshold missed"
```

## Environment controls

```dotenv
AMAURA_VENTURE_MIN_SCORE=70
AMAURA_VENTURE_MAX_ACTIVE_SPRINTS=1
AMAURA_VENTURE_MAX_SPRINT_BUDGET_CENTS=5000
AMAURA_VENTURE_FOUNDER_REVIEW_MINUTES=20
```

Budget values are policy ceilings, not authorisation to spend. Actual payments always require founder action.
