## LNbits Architecture Overview

LNbits connects Lightning backends and fiat payment providers to a shared platform for wallets, payments, and extensions. The diagram below shows three parts of that architecture:

- Backends and providers supply the external payment services on the left.
- The LNbits instance contains the application layer, core platform, and payment integrations in the center.
- Users, merchants, and applications access LNbits through its web interface and REST API, while the extension marketplace provides extensions to install and update on the right.

This is a **conceptual** overview: the connections summarize integration and access paths, rather than individual payment flows or internal implementation details.



```mermaid

flowchart TB
    users["Users · Merchants · Applications"]

    subgraph lnbits["LNbits instance"]
        direction TB

        interface["Web interface · REST API"]

        subgraph core["Core platform"]
            direction TB
            wallets["Wallets & accounts"]
            payments["Payment orchestration"]
            admin["Administration & API access"]
        end

        extensions["Installed extensions<br/>POS · Paywalls · Tickets · Other apps"]

        lightning["Lightning backend integration"]
        fiat["Fiat provider integration"]

        interface --> wallets
        interface --> extensions
        admin -.-> wallets
        admin -.-> extensions
        wallets --> payments
        extensions -->|"Payment requests"| payments

        payments --> lightning
        payments --> fiat
    end

    subgraph backends["Lightning backends"]
        direction LR
        nodes["Self-hosted nodes"]
        hosted["Hosted Lightning services"]
    end

    subgraph providers["Fiat providers"]
        direction LR
        cards["Card payment providers"]
        paypal["PayPal"]
    end

    marketplace["Extension marketplace<br/>Discover & distribute extensions"]

    users --> interface
    lightning <-->|"Backend API"| nodes
    lightning <-->|"Backend API"| hosted
    fiat <-->|"Provider API & callbacks"| cards
    fiat <-->|"Provider API & callbacks"| paypal
    marketplace -.->|"Install / update"| extensions

    classDef entry fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef platform fill:#eef2ff,stroke:#6366f1,color:#312e81
    classDef extension fill:#f3e8ff,stroke:#9333ea,color:#581c87
    classDef lightning fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef fiat fill:#dcfce7,stroke:#16a34a,color:#14532d

    class users,interface entry
    class wallets,payments,admin platform
    class extensions,marketplace extension
    class lightning,nodes,hosted lightning
    class fiat,cards,paypal fiat
```
