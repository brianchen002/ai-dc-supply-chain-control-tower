# Workflow Diagrams — OpsPilot

Rendered natively by GitHub (Mermaid). Source of truth for the flows the
prototype implements; decision thresholds live in
[03-decision-rules.md](03-decision-rules.md).

## 1. Order lifecycle (intake → delivery)

```mermaid
flowchart TD
    A[Order received\nweb / EDI / phone] --> B{Intake validation}
    B -- "payment pending" --> E1[PAYMENT_HOLD\n→ Finance Ops]
    B -- "address fails carrier check" --> E2[ADDRESS_INVALID\n→ Order Management]
    B -- "duplicate signature" --> E3[DUPLICATE_ORDER\n→ Order Management]
    B -- valid --> C{Inventory check\nATP at assigned DC}
    C -- "ATP = 0" --> E4[STOCKOUT\n→ Inventory Ops]
    C -- "0 < ATP < qty" --> E5[PARTIAL_FULFILLMENT\n→ Inventory Ops]
    C -- covered --> D[Allocate & reserve]
    D --> F[Priority-ranked\nfulfillment queue]
    F --> G{Picked & shipped\nbefore promise?}
    G -- "no, promise ≤24h or past" --> E6[SLA_RISK\n→ Fulfillment Ops]
    G -- yes --> H[In transit]
    H --> I{Delivered by\npromised date?}
    I -- "no scan past promise" --> E7[CARRIER_DELAY\n→ Logistics]
    I -- yes --> J[Delivered ✓]
    E1 & E2 & E3 & E4 & E5 --> K[Exception Center\nAI-recommended actions]
    E6 & E7 --> K
    K -- resolved --> F
```

## 2. Exception management loop

```mermaid
flowchart LR
    S[(Operational state\norders · inventory · shipments)] --> D[Detection engine\nscans state, 8 types]
    D --> T[Classify severity\ncritical / high / medium / low]
    T --> R[Route to owning team\nper decision rules §3]
    R --> Q[Exception queue]
    Q --> AI[AI workflow 2:\ncontext + SOP → next actions]
    AI --> H{Operator decides}
    H -- execute --> X[Resolve & document]
    H -- "trigger met" --> ESC[Escalate per SOP]
    ESC --> X
    X --> S
```

Key property: detection is **stateless re-derivation** — an exception exists
if and only if the data condition holds. Resolving the underlying state
(inventory arrives, payment clears) removes the condition.

## 3. AI workflow sequence (workflow 2 — recommend actions)

```mermaid
sequenceDiagram
    actor Op as Operator
    participant UI as Exception Center
    participant CTX as Context builder (SQL)
    participant RET as SOP retriever (TF-IDF)
    participant LLM as LLM client

    Op->>UI: open exception EXC-0002
    UI->>CTX: gather live context
    CTX-->>UI: order, customer tier, ATP by DC, inbound POs, shipment scans
    UI->>RET: query by exception type
    RET-->>UI: top-k SOP sections + citations
    alt ANTHROPIC_API_KEY set
        UI->>LLM: system guardrails + context JSON + SOP excerpts
        LLM-->>UI: grounded actions with SOP citations
    else offline mode
        UI->>UI: deterministic playbook over same context
    end
    UI-->>Op: situation · numbered actions · escalation check
```

## 4. System architecture

```mermaid
flowchart TB
    subgraph APP[Streamlit app]
        P1[Ops Dashboard] --- P2[Fulfillment Queue] --- P3[Exception Center] --- P4[Ops Copilot]
    end
    subgraph AIL[AI workflow layer]
        W1[Exception summarizer] --- W2[Action recommender] --- W3[SOP Q&A]
        LC[Pluggable LLM client\nClaude API ⇄ offline fallback]
        W1 & W2 & W3 --> LC
    end
    subgraph BIZ[Business logic - Python]
        PE[Priority engine] --- XE[Exception detection] --- ATP[ATP checks]
    end
    subgraph DATA[Data layer]
        GEN[Synthetic data generator] --> DB[(SQLite · 8 tables)]
        SQLQ[Named SQL queries] --> DB
        SOP[SOP corpus · 6 markdown docs]
    end
    APP --> AIL
    APP --> BIZ
    AIL --> BIZ
    BIZ --> DB
    AIL --> SOP
```
