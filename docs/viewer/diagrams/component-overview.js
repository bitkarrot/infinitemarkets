window.DIAGRAM_DATA = window.DIAGRAM_DATA || {};
window.DIAGRAM_DATA['component-overview'] = {
  title: 'Component Diagram — As Built',
  source: 'docs/architecture-overview.md — §1 (Releases A + B + post-03.1 surfaces)',
  legend: [
    { color: '#ffd23d', label: 'Browsers' },
    { color: '#ff6a1f', label: 'LNbits host services' },
    { color: '#4fdc9a', label: 'infinitemarkets extension' },
    { color: '#ff5aa8', label: 'Outbound destinations' }
  ],
  mermaid: `flowchart TD
    subgraph Browsers[Browsers]
        AdminSPA["Admin SPA (Vue3 / Quasar)<br/>merchant browser"]
        BuyerUI["Public pages (buyer, anonymous)<br/>/p/{pk}/{d} · /public/... · /order#token"]
    end

    subgraph Host[LNbits host]
        Payments["LNbits payments service<br/>bolt11 via configured wallet backend"]

        subgraph Ext[infinitemarkets extension]
            direction TB
            AdminAPI["Admin API /api/v1/*<br/>check_user_exists → LNbits user"]
            Modules["catalog.py · merchant.py<br/>themes.py · relay.py<br/>products, collections, shipping,<br/>keys, relays, themes"]
            Views["views.py — server-rendered HTML<br/>nip89.py: public projections +<br/>availability + rate limits<br/>themes.emit_css → scoped .gm-public"]
            PublicAPI["Public API /api/v1/public/* (no auth)<br/>catalog reads (public projections)<br/>POST /checkout · GET /order-status (bearer)"]
            Checkout["checkout.py · orders.py · settlement.py"]
            ExtDB[("Extension SQLite tables<br/>same LNbits DB file<br/>infinitemarkets_*")]
            Workers["Background workers (tasks.py)<br/>outbox_publisher 5s · relay_manager 30s<br/>email_sender 5s · reservation_expiry 30s<br/>reconciliation 60s · retention_pruner 24h"]
            Outbox["outbox.py — durable intent queue<br/>claim → render event from CURRENT state<br/>→ sign via keystore → send → record ACK"]
            Transport["transport.py — owned Nostr client (nostr-sdk)<br/>wss only · converges to configured relays"]
        end
    end

    subgraph Dest[Outbound destinations]
        Relays["Merchant-configured public relays<br/>wss://..."]
        PubTable[("relay_publications table<br/>per-relay ACK evidence")]
        Blossom["Blossom / media endpoints<br/>config only — future media uploads"]
    end

    AdminSPA -->|"session cookie"| AdminAPI
    AdminAPI --> Modules
    BuyerUI -->|"GET"| Views
    BuyerUI -->|"XHR + X-Order-Token header"| PublicAPI
    PublicAPI --> Checkout
    Modules --> ExtDB
    Views --> ExtDB
    Checkout -->|"create_invoice"| Payments
    Payments -->|"payment status"| Checkout
    Checkout --> ExtDB
    Workers <--> ExtDB
    Workers -.->|"reconcile payment status"| Payments
    Workers --> Outbox
    Outbox --> Transport
    Transport -->|"send_to(urls) — outbound only, Release A"| Relays
    Relays -.->|"inbound: kind 1059 gift-wrapped orders (Release B)"| Transport
    Transport -->|"record ACK / reject / timeout"| PubTable
    Transport -.->|"configured, not used yet"| Blossom`,

  styles: {
    light: `    classDef browserNode fill:#ffd23d,stroke:#111111,stroke-width:2px,color:#111111
    classDef hostNode fill:#ff6a1f,stroke:#111111,stroke-width:2px,color:#111111
    classDef extNode fill:#4fdc9a,stroke:#111111,stroke-width:2px,color:#111111
    classDef extDB fill:#fffdf7,stroke:#111111,stroke-width:2px,color:#111111
    classDef sinkNode fill:#ff5aa8,stroke:#111111,stroke-width:2px,color:#111111
    classDef sinkDB fill:#fffdf7,stroke:#111111,stroke-width:2px,color:#111111

    class AdminSPA,BuyerUI browserNode
    class Payments hostNode
    class AdminAPI,Modules,Views,PublicAPI,Checkout,Workers,Outbox,Transport extNode
    class ExtDB extDB
    class Relays,Blossom sinkNode
    class PubTable sinkDB

    style Browsers fill:#fcefcd,stroke:#111111,stroke-width:2.5px,color:#111111
    style Host fill:#ffe1cf,stroke:#111111,stroke-width:2.5px,color:#111111
    style Ext fill:#d8f3e3,stroke:#111111,stroke-width:2.5px,color:#111111
    style Dest fill:#ffe0ec,stroke:#111111,stroke-width:2.5px,color:#111111

    linkStyle default stroke:#111111,stroke-width:2.5px`,

    dark: `    classDef browserNode fill:#ffd23d,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef hostNode fill:#ff6a1f,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef extNode fill:#4fdc9a,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef extDB fill:#26251f,stroke:#f4f0e6,stroke-width:2px,color:#f4f0e6
    classDef sinkNode fill:#ff5aa8,stroke:#f4f0e6,stroke-width:2px,color:#111111
    classDef sinkDB fill:#26251f,stroke:#f4f0e6,stroke-width:2px,color:#f4f0e6

    class AdminSPA,BuyerUI browserNode
    class Payments hostNode
    class AdminAPI,Modules,Views,PublicAPI,Checkout,Workers,Outbox,Transport extNode
    class ExtDB extDB
    class Relays,Blossom sinkNode
    class PubTable sinkDB

    style Browsers fill:#322d1b,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6
    style Host fill:#342517,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6
    style Ext fill:#1e2f24,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6
    style Dest fill:#331b26,stroke:#f4f0e6,stroke-width:2.5px,color:#f4f0e6

    linkStyle default stroke:#f4f0e6,stroke-width:2.5px`
  },

  sections: [
    {
      heading: 'What\u2019s exposed to relays',
      bullets: [
        '<b>Outbound only in Release A.</b> The extension owns its Nostr transport (<code>services/transport.py</code>) — it does not depend on the <code>nostrclient</code> extension.',
        'Catalog edits are saved to extension tables and an <b>outbox intent</b> is queued. The <code>outbox_publisher</code> worker rebuilds the event from <b>current</b> domain state — never a stored snapshot — so retries can\u2019t publish stale data.',
        'Events are signed with the merchant key (<code>merchant_keys</code> via the keystore), sent to configured relays, and each relay\u2019s ACK/reject/timeout is recorded in <code>relay_publications</code> — the evidence behind the Publications admin tab.',
        'Relay delivery is <b>never treated as state truth</b>.',
        '<b>Inbound (Release B):</b> NIP-17 gift-wrapped buyer orders (kind 1059) are live — the inbox listener maintains cursors in <code>inbox_events</code> on <code>direction=inbox|both</code> relays.'
      ]
    },
    {
      heading: 'Published event kinds',
      bullets: [
        '<code>30402</code> — NIP-99 product listing (title, price, stock, images, specs, categories, shipping refs) on create/update.',
        '<code>30405</code> — NIP-99 collection (requires ≥1 active member by contract).',
        '<code>30406</code> — shipping option.',
        '<code>0</code> — merchant profile (name, about, picture).',
        '<code>31990</code> — NIP-89 handler info: this merchant serves <code>/p/{naddr}</code> product pages.',
        '<code>5</code> — tombstone / deletion request.',
        '<code>30017</code>/<code>30018</code> — literal NIP-15 stall + product: <b>Release C</b> (builders exist, not emitted yet).'
      ]
    },
    {
      heading: 'Never exposed',
      bullets: [
        'Orders, invoices, buyers\u2019 data, or internal state are never published.',
        'The nsec lives in <code>merchant_keys</code>, is used only for event signing, and leaves the host only on the one-time TLS POST during nsec import.',
        'Blossom/media endpoints are merchant-configurable but config-only today (no uploads yet).'
      ]
    },
    {
      heading: 'Flows within LNbits',
      bullets: [
        '<b>Catalog:</b> admin API → validated DTOs → <code>infinitemarkets_*</code> tables → outbox intents → signed NIP-99 events. The DB is authoritative; relay events are projections.',
        '<b>Orders:</b> buyer checkout → <code>checkout.py</code> reserves inventory in a transaction → LNbits <code>create_invoice</code> → order + payment rows → 201 with bearer token. The token lives in the URL fragment; status polls use <code>X-Order-Token</code>.',
        '<b>Payment truth comes only from LNbits payment state</b> — never from relay delivery.',
        '<b>Deletion:</b> soft-delete in the DB, then a kind-5 tombstone is published so the relay copy stops advertising the item; the row is kept for order/audit history.'
      ]
    }
  ]
};
