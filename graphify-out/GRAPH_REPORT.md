# Graph Report - .  (2026-07-15)

## Corpus Check
- Corpus is ~42,957 words - fits in a single context window. You may not need a graph.

## Summary
- 392 nodes · 771 edges · 29 communities (22 shown, 7 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 99 edges (avg confidence: 0.78)
- Token cost: 194,771 input · 0 output

## Community Hubs (Navigation)
- Backend API & Data Models
- Product Architecture & Planning Docs
- React Frontend Pages
- LLM Provider Abstraction
- Forecasting & Dynamic Pricing
- Knowledge Base & Q&A
- Frontend Dependencies (npm)
- Voice Concierge Architecture
- Intent & Knowledge Tests
- Recommender & Upsell Engine
- Bahamas Restaurant Data Fetcher
- Concierge Web Widget
- Synthetic Data Generator
- Voice Turn-Taking & Barge-in
- Widget Embed & Session API
- Dev Run Script
- Graycliff Frontend Assets
- PythaFlow Brand Mark
- Smart Menu Pricing
- Voice Latency Budget
- Streaming STT
- Streaming TTS
- Covers Forecast Service
- Synthetic POS Dataset

## God Nodes (most connected - your core abstractions)
1. `MenuItem` - 32 edges
2. `Order` - 21 edges
3. `Base` - 14 edges
4. `OrderItem` - 13 edges
5. `KnowledgeEntry` - 13 edges
6. `interpret()` - 13 edges
7. `Guest` - 12 edges
8. `Inventory` - 12 edges
9. `seed_if_empty()` - 12 edges
10. `LLMService` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Channel Gateway (thin adapters)` --semantically_similar_to--> `Unified API Gateway (single entry point)`  [INFERRED] [semantically similar]
  Discovery/Concierge_System_Plan.md → restaurant_aisolution.md
- `Hero Conversation Player` --semantically_similar_to--> `Voice Concierge (production)`  [INFERRED] [semantically similar]
  pythaflow-site/index.html → Graycliff/docs/Voice_Agent_Architecture.md
- `Cascaded Voice Pipeline (STT-LLM-TTS)` --semantically_similar_to--> `Voice-First Ordering & Reservation`  [INFERRED] [semantically similar]
  Discovery/Concierge_System_Plan.md → restaurant_aisolution.md
- `Staff Console (human-in-the-loop)` --semantically_similar_to--> `AI-Powered Guest Personalization`  [INFERRED] [semantically similar]
  Discovery/Concierge_System_Plan.md → restaurant_aisolution.md
- `Multi-Tenant Data Model & Memory` --semantically_similar_to--> `Multi-Tenancy (partitioned by restaurant_id)`  [INFERRED] [semantically similar]
  Discovery/Concierge_System_Plan.md → restaurant_aisolution.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Concierge System Architecture Layers** — discovery_concierge_system_plan_channel_gateway, discovery_concierge_system_plan_conversation_orchestrator, discovery_concierge_system_plan_skills_tools, discovery_concierge_system_plan_knowledge_memory, discovery_concierge_system_plan_staff_console [EXTRACTED 1.00]
- **Concierge Build Plan Document Chain** — discovery_concierge_system_plan, discovery_concierge_30_day_sprint, discovery_concierge_week1_build_spec [EXTRACTED 1.00]
- **Five Restaurant AI Modules on Unified Platform** — restaurant_aisolution_smart_menu_dynamic_pricing, restaurant_aisolution_guest_personalization, restaurant_aisolution_voice_first_ordering, restaurant_aisolution_marketing_content, restaurant_aisolution_qr_menu_upsell, restaurant_aisolution_unified_platform [EXTRACTED 1.00]
- **Voice-to-voice audio round-trip** — graycliff_docs_voice_agent_architecture_concierge_widget, graycliff_docs_voice_agent_architecture_voice_gateway, graycliff_docs_voice_agent_architecture_agent_core, graycliff_docs_voice_agent_architecture_stt, graycliff_docs_voice_agent_architecture_tts [EXTRACTED 1.00]
- **Build-vs-buy decision record** — graycliff_docs_voice_agent_architecture_cascaded_pipeline, graycliff_docs_voice_agent_architecture_managed_platform, graycliff_docs_voice_agent_architecture_realtime_s2s [EXTRACTED 1.00]
- **Vendor-blind provider isolation stack** — graycliff_readme_ai_provider_isolation, graycliff_readme_llmservice_interface, graycliff_readme_provider_wrapper [EXTRACTED 1.00]

## Communities (29 total, 7 thin omitted)

### Community 0 - "Backend API & Data Models"
Cohesion: 0.10
Nodes (51): BaseModel, DeclarativeBase, FastAPI, Base, get_db(), lifespan(), Event, Guest (+43 more)

### Community 1 - "Product Architecture & Planning Docs"
Cohesion: 0.06
Nodes (49): Concierge 30-Day Sprint (Phase 0 text-first), Write-Action Approval Flow, Eval Harness (golden-dialogue suite), Pilot Soft Launch (one venue, humans approving), WhatsApp Adapter (BSP sandbox), Concierge System Architecture & Build Plan, Build vs Buy (own the brain), Canonical Message/Event (+41 more)

### Community 2 - "React Frontend Pages"
Cohesion: 0.09
Nodes (25): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, api, App(), router (+17 more)

### Community 3 - "LLM Provider Abstraction"
Cohesion: 0.11
Nodes (20): ABC, _extract_json(), generate_marketing(), interpret_voice(), _interpret_with_llm(), _marketing_template(), _marketing_with_llm(), Voice intent extraction and marketing copy — app-core AI logic.  This module is (+12 more)

### Community 4 - "Forecasting & Dynamic Pricing"
Cohesion: 0.13
Nodes (28): PriceSuggestion, decide_suggestion(), get_forecast(), get_waste_risk(), list_suggestions(), Session, _suggestion_dict(), SuggestionDecision (+20 more)

### Community 5 - "Knowledge Base & Q&A"
Cohesion: 0.14
Nodes (28): KnowledgeEntry, One fact, policy, or FAQ the concierge may draw on.      Multi-tenant by restaur, create_entry(), delete_entry(), _entry_dict(), list_entries(), Session, search_entries() (+20 more)

### Community 6 - "Frontend Dependencies (npm)"
Cohesion: 0.07
Nodes (29): dependencies, react, react-dom, react-router-dom, recharts, devDependencies, oxlint, @types/react (+21 more)

### Community 7 - "Voice Concierge Architecture"
Cohesion: 0.08
Nodes (26): Docker Compose Stack (backend+frontend), Restaurant Actions API, Agent Core (vendor-blind), Cascaded Streaming Pipeline (chosen), Knowledge Pack, LLMService Interface (streaming + tool-use), Managed Voice-Agent Platform (rejected), Multi-tenant (restaurant_id) (+18 more)

### Community 8 - "Intent & Knowledge Tests"
Cohesion: 0.14
Nodes (13): _interpret_rule_based(), Keyword parser — keeps the demo alive without an API key.      Intent precedence, db(), make_menu(), Knowledge retrieval + voice intent classification.  These lock down the exact fa, Fresh instances per test — ORM objects must not span sessions., test_bare_mention_orders(), test_hours_question_not_reservation() (+5 more)

### Community 9 - "Recommender & Upsell Engine"
Cohesion: 0.24
Nodes (18): MenuItem, get_item(), item_dict(), list_menu(), Session, Session, recommendations(), _allowed() (+10 more)

### Community 10 - "Bahamas Restaurant Data Fetcher"
Cohesion: 0.33
Nodes (8): Any, centre_points(), fetch_details(), fetch_nearby(), main(), Return a set of latitude/longitude points that roughly cover the Bahamas.      T, Call the Nearby Search endpoint.      Parameters     ----------     lat, lng: fl, Retrieve additional fields for a place.      Returns a dictionary with ``name``,

### Community 11 - "Concierge Web Widget"
Cohesion: 0.67
Nodes (5): actionCard(), agentSay(), bubble(), esc(), submit()

### Community 12 - "Synthetic Data Generator"
Cohesion: 0.60
Nodes (4): main(), parties_for(), date, Generate a realistic synthetic dataset for the Graycliff demo.  Graycliff hasn't

### Community 13 - "Voice Turn-Taking & Barge-in"
Cohesion: 0.50
Nodes (4): Barge-in, Turn State Machine, On-device VAD (Silero WASM), Voice Gateway

### Community 14 - "Widget Embed & Session API"
Cohesion: 0.50
Nodes (4): PythaFlow Concierge Widget, Session Token API, Concierge Script-Tag Integration, Graycliff.com Layout Mockup

### Community 16 - "Graycliff Frontend Assets"
Cohesion: 0.67
Nodes (3): Graycliff Frontend Favicon (purple flow/lightning mark), Graycliff UI Icon Sprite (Bluesky, Discord, GitHub, X, Docs, Social), Vite Logo (purple lightning/flow mark)

### Community 17 - "PythaFlow Brand Mark"
Cohesion: 1.00
Nodes (3): PythaFlow Site Favicon (teal flow-loop mark), PythaFlow Flow-Loop Brand Mark (teal infinity/loop), PythaFlow Brand Identity (continuous flow loop)

## Knowledge Gaps
- **59 isolated node(s):** `dev.sh script`, `$schema`, `oxc`, `react/rules-of-hooks`, `warn` (+54 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MenuItem` connect `Recommender & Upsell Engine` to `Backend API & Data Models`, `Intent & Knowledge Tests`, `Forecasting & Dynamic Pricing`, `Knowledge Base & Q&A`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `Order` connect `Backend API & Data Models` to `Recommender & Upsell Engine`, `Forecasting & Dynamic Pricing`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `interpret()` connect `Backend API & Data Models` to `Recommender & Upsell Engine`, `LLM Provider Abstraction`, `Knowledge Base & Q&A`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `MenuItem` (e.g. with `Base` and `summary()`) actually correct?**
  _`MenuItem` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `Order` (e.g. with `Base` and `summary()`) actually correct?**
  _`Order` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Base` (e.g. with `Event` and `Guest`) actually correct?**
  _`Base` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `OrderItem` (e.g. with `Base` and `summary()`) actually correct?**
  _`OrderItem` has 4 INFERRED edges - model-reasoned connections that need verification._