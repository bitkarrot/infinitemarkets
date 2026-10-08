/* Registry of all rendered diagrams. Each entry maps to diagrams/<id>.js which
   holds the mermaid source plus structured bullet sections (long-form /
   slideshow source material). */
window.DIAGRAMS = [
  {
    id: 'lnbits-integration',
    num: '01',
    accent: '#ffd23d',
    title: 'LNbits Core Integration Architecture',
    source: 'docs/technical-specification.md — §2.1',
    kind: 'Spec contract',
    summary: 'The host boundary and runtime flow between LNbits core and the infinitemarkets extension: router mount, invoice creation, settlement callbacks, reconciliation, email, and extension-owned Nostr transport.'
  },
  {
    id: 'component-overview',
    num: '02',
    accent: '#ff5aa8',
    title: 'Component Diagram — As Built',
    source: 'docs/architecture-overview.md — §1',
    kind: 'Implementation state',
    summary: 'What is wired today: merchant admin SPA, public storefront surfaces, checkout and settlement against LNbits payments, the six background workers, and the outbox → transport → relay publication pipeline.'
  }
];
