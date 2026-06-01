# Project brief
<!-- Doc 0 — written by the USER before the CTO orchestrator session begins.
     The CTO reads this file, asks clarifying questions, and appends to
     clarification_log until shared_plan_approved is set to true.
     Do not edit clarification_log or shared_plan_approved manually. -->

---

## Identity

| Field | Value |
|---|---|
| project_id | proj-protegopay-pilot-001 |
| project_name | ProtegoPay — white-label budgeting and safer-gambling pilot |
| created_at | 2026-05-31 |
| author | Eugenio Servidio |

---

## What we are building

ProtegoPay is a B2B white-label software module for regulated online-gaming concessionaires, initially scoped as a pilot with an operator such as Sisal. The module is embedded inside the concessionaire's existing site or app and gives users voluntary budgeting, deposit monitoring, configurable alerts, short reflection pauses, spending-limit setup support and a dashboard that improves the readability of gaming-related spending. The first pilot addresses the gap between unrestricted activity and binary self-exclusion without weakening the concessionaire's existing responsible-gaming controls. ProtegoPay remains a technology supplier: it does not operate gaming accounts, handle bets, hold user funds, initiate payments under its own terms or appear as a standalone payment method. Payments remain within the concessionaire and its authorised PSP/PISP perimeter. Optional integrations with fraud-intelligence tools such as SEON or Sportradar may provide signals to the merchant's existing risk stack, but must not replace the merchant's controls. A pension or insurance journey may be assessed only in a later phase as a separate, voluntary and regulated flow outside the cashier and outside the deposit event.

---

## Domain

Fintech / RegTech / responsible gaming / B2B SaaS for regulated online gaming.

---

## Tech stack

<!-- List what you already know you want to use. Leave blank if undecided. -->

| Layer | Choice | Reason / constraint |
|---|---|---|
| Language | Undecided | To be selected after the pilot integration requirements and the concessionaire's technical standards are known. |
| Framework | Undecided | The first release must support a white-label embedded module within the concessionaire's site or app, not a standalone retail payment product. |
| Database | Undecided | Must support strict data minimisation, segregation by purpose, access control, retention rules and complete audit trails. Raw vulnerability-related data must not be broadly shared with the concessionaire. |
| Auth | Concessionaire-authenticated session / SSO for the pilot; exact mechanism undecided | No autonomous ProtegoPay KYC onboarding in the first pilot. Any identity-verification component must remain under the relevant regulated actor's process. |
| Hosting / infra | Undecided; EU/EEA-oriented deployment to be assessed | Must support security due diligence, high availability, business-continuity planning, an exit plan, incident handling and third-party outsourcing controls compatible with the regulated ecosystem. |
| CI/CD | Undecided | Must include code review, security testing, dependency controls, environment separation, auditability and controlled releases before integration into a Tier-1 operator environment. |
| Other | White-label SaaS/UX and rules engine; API integration with the concessionaire; optional antifraud signal integration; no ProtegoPay payment method; no in-cashier PIP split | Sisal or another concessionaire remains responsible for the gaming relationship and cashier. Payments remain managed by the concessionaire and an authorised PSP/PISP. SEON/Sportradar-type integrations act only as signal providers inside the merchant's risk stack. |

---

## Hard constraints

<!-- Things that cannot change: compliance requirements, existing systems to integrate with,
     budget ceilings, team skill limits, deadlines, licensing restrictions. -->

- The first pilot must be structured as a B2B white-label technology service embedded within the concessionaire's perimeter. ProtegoPay must not appear as an autonomous retail-facing layer between the user and the concessionaire.
- The concessionaire remains responsible for the gaming account, cashier, deposits, responsible-gaming controls, statutory limits, self-exclusion and the relationship with the player.
- ProtegoPay must not hold funds, receive deposits on a technical transit account or initiate payment services under its own customer-facing terms.
- Payments must be managed only by the concessionaire and its authorised PSP/PISP. The pilot must not present “ProtegoPay” as a payment method.
- The first pilot must not include contextual split payments from a gaming deposit toward a PIP, pension product, insurance policy or savings product.
- The first pilot must not include PIP subscription fees, fees on PIP-directed flows or any commercial journey that could qualify ProtegoPay as an insurance or pension-product distributor.
- The first pilot must exclude any “fun bonus”, cashback-like mechanism, symbolic reward, gamified accrual mechanic or messaging that could incentivise gaming activity.
- Product wording must remain neutral and consumer-protective: budgeting, spending awareness, voluntary self-control tools, deposit monitoring, reduction of spending spikes and clearer account visibility. Avoid claims such as “reduction of guilt”, “double win”, “responsible retention”, “increase LTV”, “win while you play” or equivalent language.
- A DPIA must be completed before the pilot. Data flows, controller/processor roles, minimisation rules, retention limits, access controls and audit trails must be documented before implementation.
- Any intervention with a potentially significant effect on the user must avoid fully automated decision-making without appropriate safeguards. The safe default is warnings, dashboards, revocable suggestions and human review for incisive actions.
- Antifraud integrations must be subordinate to the concessionaire's existing controls and designed to minimise false positives, duplicated decisioning and conflicting risk outcomes.
- The implementation must include idempotency, reconciliation, timeout handling, monitoring, incident response, business-continuity planning and an exit plan suitable for a regulated partner environment.
- Any future pension or insurance feature requires a separate journey, separate information notices, regulated-partner ownership, demands-and-needs assessment, explicit consent and written legal validation before development.

---

## Non-goals

<!-- Explicitly list what this project will NOT do, to keep scope clear. -->

- Operate a gaming platform, manage odds or bets, replace the concessionaire or participate autonomously in gaming collection.
- Become a standalone consumer wallet, payment gateway, PSP/PISP or customer-facing payment method in the first pilot.
- Hold user funds or perform an atomic split of a gaming deposit between the concessionaire and a PIP, insurance or savings product.
- Distribute, recommend or sell a PIP, pension product, insurance product or investment product during the first pilot.
- Use bonuses, reward mechanics, gamification, “double win” framing or guilt-reduction messaging to encourage continued gaming activity.
- Replace the concessionaire's KYC/AML, self-exclusion, responsible-gaming or antifraud systems.
- Create a medical-service funnel or structured in-app referral flow to psychotherapists or associations during the first pilot.
- Run a direct-to-consumer acquisition model linked to gaming activity during the first pilot.

---

## Team

| Field | Value |
|---|---|
| team_size | To be confirmed. One technical co-founder / CTO is currently identified; implementation staffing for the pilot is not yet fixed. |
| experience_level | Mixed founding team. Technical ownership sits with a cybersecurity-focused CTO; additional product, backend, frontend, DevOps and compliance delivery capacity must be confirmed. |
| working_style | To be confirmed. The pilot will require close coordination with the concessionaire, PSP/PISP, privacy counsel and any antifraud provider. |

---

## Known risks

<!-- Anything you're already worried about: unclear requirements, external API
     dependencies, performance unknowns, etc. -->

- Scope creep could cause ProtegoPay to be perceived as participating in gaming collection rather than acting as a pure technology supplier.
- A customer-facing payment journey, proprietary payment terms or direct payment promotion could attract PSP/PISP or agent-in-payment-services perimeter issues.
- Profiling gaming-related deposits, limits, pauses, frequency and vulnerability signals creates a high-risk privacy context and may expose sensitive inferences.
- The pilot may duplicate controls already operated by Sisal or another Tier-1 concessionaire unless the product gap is defined precisely before development.
- Any touchpoint inside the cashier may increase abandonment, latency or support load. The maximum acceptable UX friction is not yet known.
- Antifraud signals may create false positives, duplicated controls or inconsistent outcomes when combined with the merchant's existing risk engines.
- Third-party dependencies, including PSP/PISP, identity, analytics and antifraud providers, create SLA, cybersecurity, outsourcing and incident-management risk.
- The exact integration surface, API contracts, data model, hosting model and deployment requirements remain to be clarified with the concessionaire.
- The technical delivery team size and operating model are not yet fixed.
- Any future PIP or insurance extension remains subject to legal, technical, commercial and partner validation and may be unsuitable for implementation.

---

## Reference material

<!-- Links or file paths to specs, mockups, competitor products, prior art, etc. -->

- `/mnt/data/Red team due diligence su ProtegoPay.pdf`
- `/mnt/data/Agisci come un team multidisciplinare di due dilig.pdf`
- `/mnt/data/Analisi ProtegoPay_ Mercato, Competitor, Regolamen....pdf`
- `/mnt/data/Piano Marketing ProtegoPay Fintech Insurtech.pdf`
- `/mnt/data/Definizione Mercato Gioco Online Italia.pdf`
- `/mnt/data/Team.pdf`
- `/mnt/data/ProtegoPay - Business Plan 0-4 anni (PIP).xlsx`
- Project discussion history: ProtegoPay, 2i3T, Trustly and preparation for operator discussions.

---

## Clarification log
<!-- MANAGED BY CTO ORCHESTRATOR — do not edit manually.
     Each entry is appended after a round-trip clarification exchange. -->

<!-- format per entry:
round: 1
question: "..."
answer: "..."
resolved: true
-->

---

## Shared plan

<!-- MANAGED BY CTO ORCHESTRATOR — written once clarification is complete. -->

shared_plan_approved: false

<!-- summary: written by CTO after all rounds resolved -->
<!-- key_decisions: [] -->
<!-- open_assumptions: [] -->
