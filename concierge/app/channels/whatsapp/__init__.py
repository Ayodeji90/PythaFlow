"""WhatsApp channel (Day 15).

The concierge brain does not change for WhatsApp: this package only maps the
BSP's wire format to the canonical InboundMessage (adapter), sends the reply
back (client), and delivers proactive outbound via the notify() seam
(transport). Exactly one new adapter, exactly the existing pipeline.
"""
