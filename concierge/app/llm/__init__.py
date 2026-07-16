"""LLM orchestration seam.

Three layers, deliberately separated so the app core never touches a vendor SDK:

    app core  ->  LLMService (interface)  ->  Provider wrapper  ->  vendor API

- `service.LLMService`   the stable, app-facing interface (generate(msgs, tier))
- `providers/*`          one thin wrapper per vendor shape (swappable)
- `factory.build_llm_service`  picks the provider from Settings
"""
