window.DIAGRAM_DATA = window.DIAGRAM_DATA || {};
window.DIAGRAM_DATA['lnbits-integration'] = {
  title: 'LNbits Core Integration Architecture',
  source: 'docs/technical-specification.md — §2.1',
  legend: [
    { color: '#ffd23d', label: 'Clients & network' },
    { color: '#ff6a1f', label: 'LNbits core (host & settlement authority)' },
    { color: '#4fdc9a', label: 'infinitemarkets extension (commerce authority)' }
  ],
  mermaid: `flowchart LR
    subgraph Clients[Clients and network]
        Merchant[Merchant browser]
        Buyer[Buyer browser or Nostr client]
        Lightning[Lightning Network]
        Relays[Nostr relays]
    end

    subgraph Core[LNbits core - host and settlement authority]
        Host[FastAPI host and extension loader]
        Identity[Authentication, wallet ownership, and exchange rates]
        InvoiceService[Invoice and payment query services]
        CorePayments[(Authoritative core payment records)]
        Funding[Configured funding source]
        Tasks[TaskManager invoice dispatcher]
        Notify[Notification service and host SMTP]
    end

    subgraph Gamma[infinitemarkets extension - commerce authority]
        Boundary[Extension routes and lifecycle hooks]
        Services[Checkout, product/category, order, and settlement services]
        PaymentAdapter[LNbits payment adapter]
        Workers[Reconciliation, inbox, and outbox workers]
        GammaDB[(Namespaced extension database)]
        Transport[Direct relay-aware Nostr transport]
    end

    Host -->|1. Mount router; run migrations; call start and stop hooks| Boundary
    Merchant -->|2. Admin HTTP requests| Host
    Buyer -->|2. Public checkout and status polling| Host
    Boundary --> Services
    Boundary -->|3. Authenticate; verify wallet; obtain rates| Identity
    Services -->|Domain transactions and reservations| GammaDB
    Services --> PaymentAdapter
    PaymentAdapter -->|4. create_invoice with extension and external_id| InvoiceService
    InvoiceService -->|Create invoice| Funding
    InvoiceService -->|Persist incoming Payment| CorePayments
    Funding <-->|5. Invoice and settlement| Lightning
    Funding -->|Settlement detected by core| CorePayments
    CorePayments -->|Settled Payment notification| Tasks
    Tasks -->|6. Registered infinitemarkets callback| Services
    Services -->|Consume reservation; confirm order; enqueue messages| GammaDB
    Workers -->|7. Query status or exact external_id after gaps or restart| InvoiceService
    Workers -->|8. Send queued order emails via host SMTP| Notify
    InvoiceService --> CorePayments
    Workers <--> GammaDB
    GammaDB -->|Pending publication intents| Transport
    Relays -->|Encrypted orders and messages| Transport
    Transport -->|Durably admit before processing| GammaDB
    Transport -->|Signed product, collection and order events| Relays`,

  styles: {
    light: `    classDef clientNode fill:#ffd23d,stroke:#111111,stroke-width:2px,color:#111111
    classDef coreNode fill:#ff6a1f,stroke:#111111,stroke-width:2px,color:#111111
    classDef coreDB fill:#fffdf7,stroke:#111111,stroke-width:2px,color:#111111
    classDef gammaNode fill:#4fdc9a,stroke:#111111,stroke-width:2px,color:#111111
    classDef gammaDB fill:#fffdf7,stroke:#111111,stroke-width:2px,color:#111111

    class Merchant,Buyer,Lightning,Relays clientNode
    class Host,Identity,InvoiceService,Funding,Tasks,Notify coreNode
    class CorePayments coreDB
    class Boundary,Services,PaymentAdapter,Workers,Transport gammaNode
    class GammaDB gammaDB

    style Clients fill:#fcefcd,stroke:#111111,stroke-width:2.5px,color:#111111
    style Core fill:#ffe1cf,stroke:#111111,stroke-width:2.5px,color:#111111
    style Gamma fill:#d8f3e3,stroke:#111111,stroke-width:2.5px,color:#111111

    linkStyle default stroke:#111111,stroke-width:2.5px`,

    dark: `    classDef clientNode fill:#ffd23d,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef coreNode fill:#ff6a1f,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef coreDB fill:#26251f,stroke:#f4f0e6,stroke-width:2px,color:#f4f0e6
    classDef gammaNode fill:#4fdc9a,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef gammaDB fill:#26251f,stroke:#f4f0e6,stroke-width:2px,color:#f4f0e6

    class Merchant,Buyer,Lightning,Relays clientNode
    class Host,Identity,InvoiceService,Funding,Tasks,Notify coreNode
    class CorePayments coreDB
    class Boundary,Services,PaymentAdapter,Workers,Transport gammaNode
    class GammaDB gammaDB

    style Clients fill:#322d1b,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6
    style Core fill:#342517,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6
    style Gamma fill:#1e2f24,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6

    linkStyle default stroke:#f4f0e6,stroke-width:2.5px`
  },

  sections: [
    {
      heading: 'Runtime flow (numbered edges)',
      bullets: [
        '<b>1 · Mount.</b> LNbits discovers the extension, mounts its <code>APIRouter</code>, runs its DB migrations, and calls <code>infinitemarkets_start()</code> / <code>infinitemarkets_stop()</code> for managed background work.',
        '<b>2 · Entry.</b> All HTTP traffic enters through the LNbits FastAPI host. Merchant routes get LNbits auth and wallet-ownership checks; public checkout stays capability- and rate-limit constrained (§5, §15).',
        '<b>3 · Auth & rates.</b> The extension authenticates via core identity services, verifies wallet ownership, and obtains exchange rates.',
        '<b>4 · Invoicing.</b> Invoice creation crosses the boundary only through the LNbits payment service with <code>extension="infinitemarkets"</code> and <code>external_id="infinitemarkets:&lt;order.id&gt;"</code>. Core persists the authoritative incoming payment; the funding source handles Lightning.',
        '<b>5 · Settlement.</b> The funding source reports settlement to core, which records it in authoritative payment records.',
        '<b>6 · Dispatch.</b> TaskManager calls the extension\u2019s registered invoice listener, which validates extension, external id, wallet, amount, and metadata before atomically confirming the order (§8.3).',
        '<b>7 · Reconciliation.</b> Workers independently query core payment state after startup, callback gaps, or uncertain invoice creation (§8.2, §8.7).',
        '<b>8 · Email.</b> Order emails queue in <code>email_queue</code> and are delivered by a leased worker through the host\u2019s configured SMTP (§8.8).'
      ]
    },
    {
      heading: 'Ownership boundaries',
      bullets: [
        'The extension owns categories, products, collections, inventory, reservations, orders, inbox, outbox, and local payment-projection state in its <b>namespaced database</b>.',
        'It <b>MUST NOT</b> write LNbits core payment tables directly.',
        'Nostr transport is <b>extension-owned</b> and reaches relays directly; relays are never authoritative for inventory or settlement.',
        'The extension stores no SMTP or spend credentials and its code policy forbids outgoing-payment APIs — but native host process privilege is <b>not</b> a spend-capability sandbox (§8.3).'
      ]
    }
  ]
};
