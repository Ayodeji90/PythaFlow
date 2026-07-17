"""Channel adapters. Each one only normalises its provider's payload into an
`InboundMessage` and renders `OutboundChunk`s back — the shared pipeline in
`base.py` does everything else, identically for every channel."""
